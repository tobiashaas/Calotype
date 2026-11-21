# Calotype AI Engine — Scientific Foundations & Literature

This document outlines the state-of-the-art computational photography, deep learning, and color science research underpinning the **Calotype 2.0 AI Engine**.

Rather than modifying pixels destructively (like conventional generative image models), Calotype operates as a **differentiable parametric photo editor**: it analyzes image semantics, lighting, and human subjects to predict optimal, non-destructive Adobe Camera Raw / Lightroom develop settings.

---

## 1. Differentiable Parametric Photo Editing & Exposure Modeling

Traditional neural networks hallucinate or interpolate pixels, often introducing artifacts, destroying RAW sensor metadata, or limiting export resolution. Calotype builds on literature that formulates photo enhancement as learning continuous parameters for a physical raw rendering pipeline.

* **Hu, Y., He, H., Xu, C., See, B., & Du, R. (Stanford, MIT, Microsoft Research)**  
  *Exposure: A Differentiable Framework for Parametric Photo Editing.*  
  Formulates image enhancement using reinforcement learning and differentiable filters that directly map to classic photo processing operations (curves, exposure, contrast).
* **Moran, N., McDonagh, S., & Slabaugh, G. (CVPR)**  
  *DeepLPF: Deep Local Parametric Filters for Image Enhancement.*  
  Demonstrates that predicting localized parametric adjustments retains full sensor fidelity and operates at arbitrary resolutions with zero quality degradation.

---

## 2. Deep White-Balance & Chromatic Adaptation

Predicting accurate white balance across mixed-lighting environments (e.g. indoor warm ambient light combined with daylight windows) is a classic problem in photography.

* **Afifi, M., & Brown, M. S. (CVPR 2020)**  
  *Deep White-Balance Editing.*  
  Models illuminant estimation directly from RAW and sRGB sensor data, enabling multi-task deep networks to re-render photos under target chromatic temperatures.
* **Cheng, Y., & Afifi, M. (WACV 2026)**  
  *Perception-Inspired Color Space Design for Photo White Balance Editing.*  
  Investigates color space transformations specifically designed for perceptual white-balance correction, separating illuminant bias from creative color grading.

---

## 3. High-Efficiency Single-Pass Multi-Task Backbones

Calotype 2.0 replaces legacy multi-model cascades with a modern, unified multi-task vision backbone running in a single forward pass (< 15 ms).

* **Qin, D., Leichner, C., Delakis, M., et al. (Google Research, 2024)**  
  *MobileNetV4 — Universal Models for Mobile and Edge Devices.*  
  Optimized for modern edge NPUs and GPUs (including Apple Neural Engine and Qualcomm Hexagon), providing Pareto-optimal accuracy and sub-3ms latency.
* **Woo, S., Debnath, S., Hu, R., Chen, X., Liu, Z., Kweon, I. S., & Xie, S. (CVPR 2023 / Meta AI)**  
  *ConvNeXt V2: Co-designing Network Design and Masked Autoencoders.*  
  A pure convolutional architecture with modern transformer-like inverted bottlenecks, excelling at multi-scale tone analysis and spatial skin protection.

---

## 4. Sequence Consistency & Temporal Coherence (ConOpt)

In reportage and burst photography, frame-to-frame variations in exposure and color temperature create distracting visual flicker in galleries.

* **Energy-Based Multi-Frame Consistency (EBM)**  
  By minimizing an energy function representing the perceptual distance between adjacent frames in a burst, the sequence optimization engine smooths transition jumps without sacrificing scene-level dynamic range.
* **Gharbi, M., Chen, J., Barron, J. T., Hasinoff, S. W., & Durand, F. (SIGGRAPH / Google Research)**  
  *Deep Bilateral Learning for Real-Time Image Enhancement.*  
  Uses bilateral grid representations to enforce spatial and temporal smoothness across related frames.

---

## 5. Universal Hardware Acceleration (ONNX Runtime Architecture)

To ensure native, zero-configuration hardware acceleration without requiring end-users to install Python or vendor-specific SDKs, the engine interfaces directly with native silicon:

* **Apple Silicon (M1–M5)**: Apple Neural Engine (ANE) & Metal via `CoreMLExecutionProvider`
* **Windows NVIDIA**: TensorRT & CUDA via `CUDAExecutionProvider`
* **Windows AMD & Intel Arc**: Direct3D 12 acceleration via `DmlExecutionProvider` (DirectML)
* **Intel Core Ultra**: NPU & iGPU acceleration via `OpenVINOExecutionProvider`
* **Windows on ARM**: Qualcomm Snapdragon X Elite via `QNNExecutionProvider`
* **Universal CPU**: SIMD optimization via AVX-512 (x86_64) and NEON (ARM64)
