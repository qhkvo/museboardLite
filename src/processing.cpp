#include "museboard/processing.hpp"
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <numeric>
#include <sstream>
#include <stdexcept>

// Image decoding, orientation, thumbnails, palettes, CLIP preprocessing, and vector math.

namespace museboard {
cv::Mat load_image(const std::filesystem::path& path) {
    // Validate the signature rather than trusting the extension.
    std::ifstream in(path, std::ios::binary);
    std::array<unsigned char, 8> sig{};
    in.read(reinterpret_cast<char*>(sig.data()), sig.size());
    const bool png = sig == std::array<unsigned char, 8>{137,80,78,71,13,10,26,10};
    const bool jpeg = sig[0] == 255 && sig[1] == 216 && sig[2] == 255;
    if (!png && !jpeg) throw std::runtime_error("Expected a JPEG or PNG: " + path.string());
    // IMREAD_COLOR applies EXIF orientation and converts grayscale/alpha to BGR.
    // Alpha is discarded, matching Pillow's convert('RGB') in the reference.
    auto image = cv::imread(path.string(), cv::IMREAD_COLOR);
    if (image.empty()) throw std::runtime_error("Cannot decode image: " + path.string());
    if (image.total() > 40'000'000) throw std::runtime_error("Image exceeds 40 megapixels");
    return image;
}

cv::Mat thumbnail(const cv::Mat& bgr, int max_edge) {
    if (bgr.empty() || max_edge < 1) throw std::invalid_argument("Invalid thumbnail input");
    const double scale = std::min(1.0, double(max_edge) / std::max(bgr.cols, bgr.rows));
    cv::Mat result;
    cv::resize(bgr, result, {std::max(1, int(std::lround(bgr.cols * scale))),
                           std::max(1, int(std::lround(bgr.rows * scale)))}, 0, 0, cv::INTER_AREA);
    return result;
}

std::vector<PaletteColor> palette(const cv::Mat& bgr) {
    auto sample = thumbnail(bgr, 128);
    // kmeans interprets a single-channel 1x3 matrix as three scalar samples.
    // Duplicate the sole pixel to retain the intended three-component samples.
    if (sample.total() == 1) cv::resize(sample, sample, {2, 1}, 0, 0, cv::INTER_NEAREST);
    cv::Mat floating, lab;
    sample.convertTo(floating, CV_32F, 1.0 / 255.0);
    cv::cvtColor(floating, lab, cv::COLOR_BGR2Lab);
    auto points = lab.reshape(1, int(lab.total()));
    const int k = std::min(5, points.rows);
    cv::Mat labels, centers;
    // Stable seed makes this single-process prototype reproducible.
    cv::theRNG().state = 42;
    cv::kmeans(points, k, labels,
        {cv::TermCriteria::EPS | cv::TermCriteria::MAX_ITER, 50, 0.1},
        3, cv::KMEANS_PP_CENTERS, centers);
    std::vector<int> counts(k, 0);
    for (int i = 0; i < labels.rows; ++i) ++counts[labels.at<int>(i)];
    std::vector<PaletteColor> colors;
    for (int i = 0; i < k; ++i) {
        cv::Vec3f color{centers.at<float>(i, 0), centers.at<float>(i, 1), centers.at<float>(i, 2)};
        cv::Mat lab_pixel(1, 1, CV_32FC3, &color), rgb;
        cv::cvtColor(lab_pixel, rgb, cv::COLOR_Lab2RGB);
        const auto v = rgb.at<cv::Vec3f>(0, 0);
        std::ostringstream hex;
        hex << '#' << std::hex << std::setfill('0') << std::uppercase;
        for (int channel = 0; channel < 3; ++channel)
            hex << std::setw(2) << std::clamp(int(std::lround(v[channel] * 255)), 0, 255);
        colors.push_back({hex.str(), color, double(counts[i]) / points.rows});
    }
    std::stable_sort(colors.begin(), colors.end(), [](const auto& a, const auto& b) { return a.weight > b.weight; });
    // Very small images still have five slots. Padding has zero weight.
    while (colors.size() < 5) colors.push_back({colors.front().hex, colors.front().lab, 0.0});
    return colors;
}

namespace {
double cubic(double x) {
    x = std::abs(x);
    if (x < 1) return ((1.5 * x - 2.5) * x) * x + 1;
    if (x < 2) return (((-0.5 * x + 2.5) * x - 4) * x) + 2;
    return 0;
}
// Pillow-style antialiased bicubic, with byte rounding after each pass.
// OpenCV INTER_CUBIC uses a different kernel and no downsampling antialiasing.
cv::Mat resize_axis(const cv::Mat& src, int size, bool horizontal) {
    const int old_size = horizontal ? src.cols : src.rows;
    if (size == old_size) return src;
    cv::Mat dst(horizontal ? src.rows : size, horizontal ? size : src.cols, CV_8UC3);
    const double scale = double(old_size) / size;
    const double filter_scale = std::max(1.0, scale);
    const double support = 2 * filter_scale;
    for (int out = 0; out < size; ++out) {
        const double center = (out + 0.5) * scale;
        const int lo = std::max(0, int(center - support + 0.5));
        const int hi = std::min(old_size, int(center + support + 0.5));
        std::vector<double> weights;
        double sum = 0;
        for (int i = lo; i < hi; ++i) {
            const auto w = cubic((i - center + 0.5) / filter_scale);
            weights.push_back(w); sum += w;
        }
        for (auto& w : weights) w /= sum;
        const int lines = horizontal ? src.rows : src.cols;
        for (int line = 0; line < lines; ++line) {
            cv::Vec3d value{0, 0, 0};
            for (int i = lo; i < hi; ++i) {
                auto pixel = horizontal ? src.at<cv::Vec3b>(line, i) : src.at<cv::Vec3b>(i, line);
                for (int c = 0; c < 3; ++c) value[c] += pixel[c] * weights[i - lo];
            }
            auto& target = horizontal ? dst.at<cv::Vec3b>(line, out) : dst.at<cv::Vec3b>(out, line);
            for (int c = 0; c < 3; ++c) target[c] = static_cast<unsigned char>(std::clamp(int(std::floor(value[c] + 0.5)), 0, 255));
        }
    }
    return dst;
}
}

std::vector<float> clip_input(const cv::Mat& bgr) {
    if (bgr.empty() || bgr.type() != CV_8UC3) throw std::invalid_argument("CLIP expects an 8-bit BGR image");
    if (double(std::max(bgr.cols, bgr.rows)) / std::min(bgr.cols, bgr.rows) > 100)
        throw std::invalid_argument("Image aspect ratio exceeds 100:1");
    constexpr int size = 224;
    // Resize shortest edge to 224, truncate the other dimension, then center crop.
    const int width = bgr.cols <= bgr.rows ? size : int(int64_t(size) * bgr.cols / bgr.rows);
    const int height = bgr.rows <= bgr.cols ? size : int(int64_t(size) * bgr.rows / bgr.cols);
    auto resized = resize_axis(resize_axis(bgr, width, true), height, false);
    auto crop = resized(cv::Rect((width - size) / 2, (height - size) / 2, size, size));
    constexpr std::array<float, 3> mean{0.48145466f, 0.4578275f, 0.40821073f};
    constexpr std::array<float, 3> stddev{0.26862954f, 0.26130258f, 0.27577711f};
    std::vector<float> tensor(3 * size * size);
    for (int y = 0; y < size; ++y)
        for (int x = 0; x < size; ++x)
            for (int c = 0; c < 3; ++c)
                tensor[c * size * size + y * size + x] = (crop.at<cv::Vec3b>(y, x)[2 - c] / 255.0f - mean[c]) / stddev[c];
    return tensor;
}

void normalize(std::vector<float>& values) {
    double squared = 0;
    for (auto v : values) {
        if (!std::isfinite(v)) throw std::runtime_error("Non-finite embedding");
        squared += double(v) * v;
    }
    if (squared <= 1e-20) throw std::runtime_error("Zero-length embedding");
    const auto norm = std::sqrt(squared);
    for (auto& v : values) v = float(v / norm);
}
double cosine(const std::vector<float>& a, const std::vector<float>& b) {
    if (a.empty() || a.size() != b.size()) throw std::invalid_argument("Incompatible embeddings");
    double dot = 0, aa = 0, bb = 0;
    for (size_t i = 0; i < a.size(); ++i) {
        if (!std::isfinite(a[i]) || !std::isfinite(b[i])) throw std::invalid_argument("Non-finite embedding");
        dot += double(a[i]) * b[i]; aa += double(a[i]) * a[i]; bb += double(b[i]) * b[i];
    }
    if (aa <= 1e-20 || bb <= 1e-20) throw std::invalid_argument("Zero-length embedding");
    return std::clamp(dot / std::sqrt(aa * bb), -1.0, 1.0);
}
}
