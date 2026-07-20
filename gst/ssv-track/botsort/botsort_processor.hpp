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
