# T2 BoT-SORT 处理器封装实施计划

> **供执行 Agent 使用：** 实施本计划时按任务逐项完成并勾选；每个任务完成后先运行其指定验证，再创建独立提交。

**目标：** 将 `gstssvtrack.cpp` 中的 BoT-SORT 检测转换、坐标适配、算法调用和结果回写收拢到 `botsort::BoTSortProcessor`，保持插件行为和元数据契约不变。

**架构：** `gstssvtrack.cpp` 保留 BoT-SORT GObject 属性的定义与读写、`make_botsort_config()` 的参数解析、生命周期、`SsvDetectionStore`、caps 读取和 `GstVideoFrame` 映射；它在 `start()` 时以属性生成的 `TrackerConfig` 创建 `BoTSortProcessor`，并在逐帧调用中传递检测、帧尺寸、可选的 BGR 数据指针和 stride。处理器以值成员持有 `BoTSortTracker`，负责所有 `SsvDetection` 与 BoT-SORT DTO 的转换及三项跟踪字段写回，不包含 GStreamer 依赖，也不定义或默认化插件参数；除构造和最终的 `process()` 调用外，不向插件暴露 BoT-SORT 的处理步骤。

**技术栈：** C++17、GStreamer `GstBaseTransform`、GLib/GObject、Meson、GStreamer Check、现有 BoT-SORT 内核。

---

## 文件结构

| 文件 | 动作 | 责任 |
| --- | --- | --- |
| `gst/ssv-track/botsort/botsort_processor.hpp` | 新增 | 声明不依赖 GStreamer 的 BoT-SORT 接入处理器。 |
| `gst/ssv-track/botsort/botsort_processor.cpp` | 新增 | 实现检测转换、像素坐标适配、跟踪调用和三项字段回写。 |
| `gst/ssv-track/gstssvtrack.cpp` | 修改 | 保留插件生命周期和帧映射，改为委托处理器。 |
| `gst/ssv-track/meson.build` | 修改 | 将处理器实现编入 `gstssvtrack` 插件。 |
| `gst/tests/test_botsort_processor.cpp` | 新增 | 直接验证处理器跨帧 ID、状态和写回数据契约。 |
| `gst/tests/test_gst_plugins.cpp` | 修改 | 注册处理器测试组。 |
| `gst/tests/meson.build` | 修改 | 将处理器测试与实现编入 `gst-unit-tests`。 |

## 任务 1：先建立处理器契约回归测试

**文件：**

- 新增：`gst/tests/test_botsort_processor.cpp`
- 修改：`gst/tests/test_gst_plugins.cpp`
- 修改：`gst/tests/meson.build`

- [ ] **步骤 1：编写会因缺少处理器而编译失败的测试。**

创建 `gst/tests/test_botsort_processor.cpp`，覆盖两帧高分检测并断言：首帧写入正 ID 和 `SSV_TRACK_NEW`，第二帧复用 ID 并写入 `SSV_TRACK_MATCHED`；bbox、置信度、类别和类别名仍等于调用前值。测试自行显式构造 `TrackerConfig`，只验证处理器接收已解析配置后的最终调用行为，不为处理器增加默认配置、属性入口或可由插件调用的中间处理方法。

```cpp
#include "../ssv-track/botsort/botsort_processor.hpp"

#include <gst/check/gstcheck.h>

#include <cstdio>
#include <cstring>

namespace {

SsvDetection make_detection(float x1, float y1, float x2, float y2) {
    SsvDetection det{};
    det.x1 = x1;
    det.y1 = y1;
    det.x2 = x2;
    det.y2 = y2;
    det.confidence = 0.95F;
    det.class_id = 1;
    std::snprintf(det.class_name, sizeof(det.class_name), "person");
    return det;
}

botsort::TrackerConfig make_config() {
    botsort::TrackerConfig config;
    config.gmc_method = botsort::GmcMethod::kNone;
    config.enable_class_constraint = false;
    return config;
}

GST_START_TEST(test_processor_writes_tracking_fields_without_mutating_detection_contract) {
    botsort::BoTSortProcessor processor(make_config());
    std::vector<SsvDetection> first{make_detection(0.10F, 0.10F, 0.30F, 0.30F)};
    const SsvDetection first_before = first[0];

    processor.process(first, 640, 480);

    fail_unless(first[0].track_id > 0);
    fail_unless(first[0].track_state == SSV_TRACK_NEW);
    fail_unless(!first[0].occluded);
    fail_unless(first[0].x1 == first_before.x1 && first[0].y1 == first_before.y1);
    fail_unless(first[0].x2 == first_before.x2 && first[0].y2 == first_before.y2);
    fail_unless(first[0].confidence == first_before.confidence);
    fail_unless(first[0].class_id == first_before.class_id);
    fail_unless(std::strcmp(first[0].class_name, first_before.class_name) == 0);

    std::vector<SsvDetection> second{make_detection(0.11F, 0.10F, 0.31F, 0.30F)};
    const SsvDetection second_before = second[0];
    processor.process(second, 640, 480);

    fail_unless(second[0].track_id == first[0].track_id);
    fail_unless(second[0].track_state == SSV_TRACK_MATCHED);
    fail_unless(second[0].x1 == second_before.x1 && second[0].y1 == second_before.y1);
    fail_unless(second[0].x2 == second_before.x2 && second[0].y2 == second_before.y2);
    fail_unless(second[0].confidence == second_before.confidence);
    fail_unless(second[0].class_id == second_before.class_id);
    fail_unless(std::strcmp(second[0].class_name, second_before.class_name) == 0);
}
GST_END_TEST

}  // namespace

void add_botsort_processor_tests(TCase *tc) {
    tcase_add_test(tc, test_processor_writes_tracking_fields_without_mutating_detection_contract);
}
```

在 `gst/tests/test_gst_plugins.cpp` 的测试组声明区新增：

```cpp
void add_botsort_processor_tests(TCase *tc);
```

并在 `ssv_gst_suite()` 中、`add_botsort_tracker_tests(tc);` 后新增：

```cpp
add_botsort_processor_tests(tc);
```

在 `gst/tests/meson.build` 的 `gst_unit_tests` 源文件列表中加入：

```meson
'test_botsort_processor.cpp',
'../ssv-track/botsort/botsort_processor.cpp',
```

- [ ] **步骤 2：运行测试，确认当前版本失败。**

运行：

```bash
./ssv build
```

预期：编译在 `botsort_processor.hpp` 缺失处失败；这证明测试尚未被现有实现满足。

- [ ] **步骤 3：提交失败测试。**

```bash
git add gst/tests/test_botsort_processor.cpp gst/tests/test_gst_plugins.cpp gst/tests/meson.build
git commit -m "test(ssv-track): define BoT-SORT processor contract"
```

## 任务 2：实现无 GStreamer 依赖的 `BoTSortProcessor`

**文件：**

- 新增：`gst/ssv-track/botsort/botsort_processor.hpp`
- 新增：`gst/ssv-track/botsort/botsort_processor.cpp`

- [ ] **步骤 1：声明处理器的单一处理接口。**

创建 `botsort_processor.hpp`：

```cpp
#pragma once

#include "botsort_tracker.hpp"
#include "ssv_meta.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace botsort {

class BoTSortProcessor {
public:
    explicit BoTSortProcessor(TrackerConfig config);

    void process(std::vector<SsvDetection> &detections,
                 int frame_width,
                 int frame_height,
                 const std::uint8_t *frame_data = nullptr,
                 std::size_t frame_stride = 0);

private:
    BoTSortTracker tracker_;
};

}  // namespace botsort
```

- [ ] **步骤 2：实现现有插件中的转换与结果写回逻辑。**

创建 `botsort_processor.cpp`。将目前 `gstssvtrack.cpp` 中的 `ssv_to_botsort_detection`、`ssv_to_botsort_detections` 和 `apply_botsort_results` 移入该文件的匿名命名空间；保持字段逐项赋值与 `input_index` 映射不变。实现主体必须为：

```cpp
BoTSortProcessor::BoTSortProcessor(TrackerConfig config)
    : tracker_(config) {}

void BoTSortProcessor::process(std::vector<SsvDetection> &detections,
                               int frame_width,
                               int frame_height,
                               const std::uint8_t *frame_data,
                               std::size_t frame_stride) {
    auto input = ssv_to_botsort_detections(detections, frame_width, frame_height);
    FrameView frame_view;
    frame_view.data = frame_data;
    frame_view.width = frame_width;
    frame_view.height = frame_height;
    frame_view.stride = frame_stride;
    UpdateResult result = frame_data != nullptr
        ? tracker_.update(input, frame_view)
        : tracker_.update(input);
    for (auto &tracked : result.detections) {
        tracked = to_normalized_detection(tracked, frame_width, frame_height);
    }
    apply_botsort_results(detections, result.detections);
}
```

包含 `botsort_coordinates.hpp` 以使用 `to_pixel_detection()` 和 `to_normalized_detection()`。不得包含 `<gst/...>`，不得处理 `GstCaps`、`GstBuffer` 或 `GstVideoFrame`；`FrameView` 仅在该实现文件内部创建和使用，不出现在处理器头文件的调用参数中。

- [ ] **步骤 3：构建并运行新增测试，确认通过。**

运行：

```bash
./ssv build
meson test -C build gst-unit-tests --verbose
```

预期：构建成功；`test_processor_writes_tracking_fields_without_mutating_detection_contract` 通过。若完整插件扫描被缺失的 `libnvinfer.so.11` 阻断，保留失败输出，并直接运行 `build/gst/tests/gst-unit-tests`，使用项目已知的 TensorRT 库路径作为 `LD_LIBRARY_PATH` 补充验证。

- [ ] **步骤 4：提交处理器与通过的回归测试。**

```bash
git add gst/ssv-track/botsort/botsort_processor.hpp gst/ssv-track/botsort/botsort_processor.cpp gst/tests/test_botsort_processor.cpp gst/tests/test_gst_plugins.cpp gst/tests/meson.build
git commit -m "refactor(ssv-track): add BoT-SORT processor"
```

## 任务 3：将插件回调收敛为处理器委托

**文件：**

- 修改：`gst/ssv-track/gstssvtrack.cpp`
- 修改：`gst/ssv-track/meson.build`

- [ ] **步骤 1：先补充插件构建源。**

在 `gst/ssv-track/meson.build` 的 `shared_library('gstssvtrack', ...)` 源文件列表中，在 `botsort/botsort_tracker.cpp` 后加入：

```meson
'botsort/botsort_processor.cpp',
```

- [ ] **步骤 2：替换插件的算法对象和调用细节。**

在 `gstssvtrack.cpp`：

1. 用 `#include "botsort/botsort_processor.hpp"` 替换 `botsort_tracker.hpp`、`botsort_coordinates.hpp` 与 `botsort_types.hpp` 的直接包含。
2. 删除文件顶部的三个静态函数：`ssv_to_botsort_detection`、`ssv_to_botsort_detections`、`apply_botsort_results`。
3. 保留 `_SsvTrack` 中全部现有 BoT-SORT 参数成员、`PROP_*` 枚举、`ssv_track_set_property()`、`ssv_track_get_property()`、`g_object_class_install_property()` 和 `ssv_track_init()` 默认值；保留插件层 `make_botsort_config(const SsvTrack *)`，不得将这些配置项、默认值或 `gmc-method` 字符串解析移入处理器。
4. 将 `_SsvTrack` 的算法对象成员替换为：

```cpp
botsort::BoTSortProcessor *processor;
```

5. 在 `ssv_track_start()` 的常规分支中创建：

```cpp
self->processor = new botsort::BoTSortProcessor(make_botsort_config(self));
```

6. 在 `ssv_track_stop()` 中删除并置空：

```cpp
delete self->processor;
self->processor = nullptr;
```

7. 在 `ssv_track_transform_ip()` 的常规分支保留 caps 获取、`GstVideoFrame` 映射和 GMC 回退 warning；将 `UpdateResult`、坐标恢复和结果写回循环替换为：

```cpp
const std::uint8_t *frame_data = nullptr;
std::size_t frame_stride = 0;
GstVideoFrame frame;
bool frame_mapped = false;
if (g_strcmp0(self->gmc_method, "none") != 0 && have_info &&
    gst_video_frame_map(&frame, &info, buf, GST_MAP_READ)) {
    frame_data = static_cast<const std::uint8_t *>(GST_VIDEO_FRAME_PLANE_DATA(&frame, 0));
    frame_stride = static_cast<std::size_t>(GST_VIDEO_FRAME_PLANE_STRIDE(&frame, 0));
    frame_mapped = true;
} else if (g_strcmp0(self->gmc_method, "none") != 0) {
    GST_WARNING_OBJECT(self, "GMC frame unavailable, falling back to no-frame update");
}

self->processor->process(det.detections, frame_width, frame_height, frame_data, frame_stride);
```

继续在调用后解除映射和释放 caps，并保留已有逐帧 `GST_DEBUG_OBJECT` 日志。`mock-track` 分支不改动。

- [ ] **步骤 3：运行结构与行为验证。**

运行：

```bash
rg -n "BoTSortTracker|ssv_to_botsort|apply_botsort_results|to_pixel_detection|to_normalized_detection" gst/ssv-track/gstssvtrack.cpp
./ssv build
meson test -C build gst-unit-tests --verbose
```

预期：第一条命令无输出；构建成功；新增 processor 回归、既有 BoT-SORT 内核回归与插件属性回归通过。插件属性回归需确认现有 `frame-rate`、各阈值、`track-buffer`、`gmc-method`、`gmc-downscale` 和 `mock-track` 仍可由 GObject 设置并在 `start()` 时生效。若 `meson test` 仅因 TensorRT 动态库缺失无法加载插件，按任务 2 的直接测试方式运行，且在交付说明中将该环境问题与处理器结果分开记录。

- [ ] **步骤 4：提交插件委托重构。**

```bash
git add gst/ssv-track/gstssvtrack.cpp gst/ssv-track/meson.build
git commit -m "refactor(ssv-track): delegate tracking to processor"
```

## 任务 4：最终回归和文档状态核对

**文件：**

- 修改：`docs/specs/2026-07-15-T2-BoT-SORT处理器封装-spec.md`，仅当实现与已确认设计有必要差异时。

- [ ] **步骤 1：执行最终验证。**

运行：

```bash
./ssv build
meson test -C build
git diff --check
git status --short
```

预期：构建成功、可执行测试通过、无空白错误；工作区只应包含本计划范围内尚未提交的文件。若测试环境缺少 TensorRT 运行时，记录准确的失败命令、缺失库名和直接运行的 BoT-SORT/插件测试结果。

- [ ] **步骤 2：核对设计状态。**

确认以下条件均成立：`gstssvtrack.cpp` 未直接使用 `BoTSortTracker` 或坐标转换函数；处理器未包含 GStreamer 头；全部 BoT-SORT 参数仍由插件以 GObject 属性公开、保存并通过 `make_botsort_config()` 传入处理器；processor 对插件只公开构造和最终的 `process()` 调用，`FrameView` 与内部处理步骤不暴露；`mock-track` 和三项跟踪字段的语义保持不变。实现与 spec 完全一致时不修改 spec。

- [ ] **步骤 3：提交最终文档调整（仅在发生时）。**

```bash
git add docs/specs/2026-07-15-T2-BoT-SORT处理器封装-spec.md
git commit -m "docs(ssv-track): record processor implementation details"
```

若 spec 未变化，此步骤不创建空提交。

