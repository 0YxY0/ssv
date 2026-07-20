#include "botsort_processor.hpp"
#include "botsort_coordinates.hpp"
namespace botsort {
namespace {
Detection ssv_to_botsort_detection(const SsvDetection &src, int input_index) {
    Detection det;
    det.x1 = src.x1; det.y1 = src.y1; det.x2 = src.x2; det.y2 = src.y2;
    det.score = src.confidence; det.class_id = src.class_id;
    det.class_name = src.class_name; det.input_index = input_index;
    det.track_id = src.track_id;
    det.track_state = static_cast<TrackState>(src.track_state);
    det.occluded = src.occluded;
    return det;
}
FrameDetections ssv_to_botsort_detections(const std::vector<SsvDetection> &src, int width, int height) {
    FrameDetections out;
    out.reserve(src.size());
    for (std::size_t i = 0; i < src.size(); ++i)
        out.push_back(to_pixel_detection(ssv_to_botsort_detection(src[i], static_cast<int>(i)), width, height));
    return out;
}
void apply_botsort_results(std::vector<SsvDetection> &dst, const FrameDetections &src) {
    for (const auto &det : src) {
        if (det.input_index < 0) continue;
        const std::size_t index = static_cast<std::size_t>(det.input_index);
        if (index >= dst.size()) continue;
        auto &out = dst[index];
        out.track_id = det.track_id;
        out.track_state = static_cast<int>(det.track_state);
        out.occluded = det.occluded;
    }
}
}
BoTSortProcessor::BoTSortProcessor(TrackerConfig config) : tracker_(config) {}
void BoTSortProcessor::process(std::vector<SsvDetection> &detections, int frame_width, int frame_height,
                               const std::uint8_t *frame_data, std::size_t frame_stride) {
    auto input = ssv_to_botsort_detections(detections, frame_width, frame_height);
    FrameView frame_view;
    frame_view.data = frame_data;
    frame_view.width = frame_width;
    frame_view.height = frame_height;
    frame_view.stride = frame_stride;
    UpdateResult result = frame_data != nullptr ? tracker_.update(input, frame_view) : tracker_.update(input);
    for (auto &tracked : result.detections)
        tracked = to_normalized_detection(tracked, frame_width, frame_height);
    apply_botsort_results(detections, result.detections);
}
}  // namespace botsort
