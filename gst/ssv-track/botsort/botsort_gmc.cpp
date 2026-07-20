#include "botsort_gmc.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#if SSV_HAS_OPENCV
#include <opencv2/calib3d.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/video/tracking.hpp>
#endif

namespace botsort {

bool
should_attempt_sparse_opt_flow(std::size_t previous_point_count) {
    return previous_point_count >= 5;
}

bool
GmcWarp::is_identity() const {
    return m00 == 1.0 && m01 == 0.0 && m02 == 0.0 && m10 == 0.0 && m11 == 1.0 && m12 == 0.0;
}

BoTSortGmc::BoTSortGmc(GmcMethod method, int downscale)
    : method_(method), downscale_(std::max(1, downscale)) {}

void
BoTSortGmc::reset() {
    initialized_ = false;
    used_fallback_identity_ = false;
#if SSV_HAS_OPENCV
    prev_gray_.release();
    prev_points_.clear();
#endif
}

GmcWarp
BoTSortGmc::identity() {
    return {};
}

bool
BoTSortGmc::used_fallback_identity() const {
    return used_fallback_identity_;
}

GmcWarp
BoTSortGmc::estimate(const FrameView *frame) {
    used_fallback_identity_ = false;
    if (method_ == GmcMethod::kNone) {
        return identity();
    }
    if (frame == nullptr || frame->data == nullptr || frame->width <= 0 || frame->height <= 0 || frame->stride == 0) {
        used_fallback_identity_ = true;
        return identity();
    }
    return estimate_sparse_opt_flow(*frame);
}

std::array<float, 4>
BoTSortGmc::apply_bbox(const GmcWarp &warp, const std::array<float, 4> &bbox) {
    const std::array<std::array<double, 2>, 4> points = {{
        {bbox[0], bbox[1]},
        {bbox[2], bbox[1]},
        {bbox[0], bbox[3]},
        {bbox[2], bbox[3]},
    }};

    float min_x = std::numeric_limits<float>::max();
    float min_y = std::numeric_limits<float>::max();
    float max_x = std::numeric_limits<float>::lowest();
    float max_y = std::numeric_limits<float>::lowest();
    for (const auto &point : points) {
        const double x = warp.m00 * point[0] + warp.m01 * point[1] + warp.m02;
        const double y = warp.m10 * point[0] + warp.m11 * point[1] + warp.m12;
        min_x = std::min(min_x, static_cast<float>(x));
        min_y = std::min(min_y, static_cast<float>(y));
        max_x = std::max(max_x, static_cast<float>(x));
        max_y = std::max(max_y, static_cast<float>(y));
    }
    return {min_x, min_y, max_x, max_y};
}

#if SSV_HAS_OPENCV
namespace {

GmcWarp to_warp(const cv::Mat &affine) {
    GmcWarp warp;
    warp.m00 = affine.at<double>(0, 0);
    warp.m01 = affine.at<double>(0, 1);
    warp.m02 = affine.at<double>(0, 2);
    warp.m10 = affine.at<double>(1, 0);
    warp.m11 = affine.at<double>(1, 1);
    warp.m12 = affine.at<double>(1, 2);
    return warp;
}

}  // namespace
#endif

GmcWarp
BoTSortGmc::estimate_sparse_opt_flow(const FrameView &frame) {
#if !SSV_HAS_OPENCV
    (void)frame;
    used_fallback_identity_ = true;
    return identity();
#else
    cv::Mat bgr(frame.height, frame.width, CV_8UC3, const_cast<std::uint8_t *>(frame.data), frame.stride);
    cv::Mat gray;
    cv::cvtColor(bgr, gray, cv::COLOR_BGR2GRAY);
    if (downscale_ > 1) {
        const int width = std::max(1, gray.cols / downscale_);
        const int height = std::max(1, gray.rows / downscale_);
        cv::resize(gray, gray, cv::Size(width, height));
    }

    std::vector<cv::Point2f> curr_points;
    cv::goodFeaturesToTrack(gray, curr_points, 1000, 0.01, 1.0);
    GmcWarp warp = identity();

    if (!initialized_) {
        prev_gray_ = gray.clone();
        prev_points_ = curr_points;
        initialized_ = true;
        used_fallback_identity_ = true;
        return warp;
    }

    if (prev_gray_.size() != gray.size() || !should_attempt_sparse_opt_flow(prev_points_.size())) {
        prev_gray_ = gray.clone();
        prev_points_ = curr_points;
        used_fallback_identity_ = true;
        return warp;
    }

    std::vector<cv::Point2f> next_points;
    std::vector<unsigned char> status;
    std::vector<float> err;
    cv::calcOpticalFlowPyrLK(prev_gray_, gray, prev_points_, next_points, status, err);
    std::vector<cv::Point2f> src;
    std::vector<cv::Point2f> dst;
    for (std::size_t i = 0; i < status.size(); ++i) {
        if (status[i]) {
            src.push_back(prev_points_[i]);
            dst.push_back(next_points[i]);
        }
    }

    if (src.size() >= 5) {
        const cv::Mat affine = cv::estimateAffinePartial2D(src, dst, cv::noArray(), cv::RANSAC);
        if (!affine.empty()) {
            warp = to_warp(affine);
            if (downscale_ > 1) {
                warp.m02 *= downscale_;
                warp.m12 *= downscale_;
            }
            used_fallback_identity_ = false;
        } else {
            used_fallback_identity_ = true;
        }
    } else {
        used_fallback_identity_ = true;
    }

    prev_gray_ = gray.clone();
    prev_points_ = curr_points;
    return warp;
#endif
}

}  // namespace botsort
