# Third-party notices

**Research use only. Not a medical device. Not for clinical decision-making.**

astril-nf's own code (this repository) is licensed under
[CC BY-NC-SA 4.0](LICENSE), the same license as [astril](https://github.com/Alexander-Ling/astril).
That license covers this repository's code only. The Docker image
(`alexanderling/ling_lab:astril-nf-*`) also bundles the third-party software and pretrained
weights below, each under its own terms. **Two of them (the HD-BET weights and the GBM_seg_v2
weights) are restricted to non-commercial use**, so the image as a whole may only be used
non-commercially.

## Pretrained weights

### GBM_seg_v2 (astril's GBM segmentation model)
- Downloaded unmodified at image build time via astril's `astril-download-models`.
- Trained only on the **BraTS 2024 BraTS-GLI (adult glioma, post-treatment) training data**
  (Synapse `syn53708249`), which is distributed under
  [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) terms ("Data can be used for
  non-commercial use only"). These weights are distributed for non-commercial research use only.
- BraTS attribution statement: *"Data used in this publication were obtained as part of the Brain
  Tumor Segmentation (BraTS) Challenge project through Synapse ID: syn53708249."*
- Publications using this model should cite the BraTS 2024 manuscripts listed in the model's own
  `CITATIONS.md` (shipped alongside its weights in the astril package), including:
  - Karargyris A, et al. *Federated benchmarking of medical artificial intelligence with
    MedPerf.* Nat Mach Intell 5, 799–810 (2023). doi:10.1038/s42256-023-00652-2
  - Correia de Verdier M, Saluja R, Gagnon L, et al. *The 2024 Brain Tumor Segmentation (BraTS) Challenge: Glioma
    Segmentation on Post-treatment MRI.* arXiv:2405.18368. doi:10.48550/arXiv.2405.18368

### HD-BET parameters (brain extraction)
- "HD-BET v1.5 parameters", Zenodo record
  [14445620](https://zenodo.org/records/14445620), by Isensee F, Schell M, Tursunova I,
  Brugnara G, Bonekamp D, Neuberger U, Wick A, Schlemmer H-P, Heiland S, Wick W, Bendszus M,
  Maier-Hein K, Kickingereder P.
- License: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Downloaded
  unmodified at image build time.
- Citation: Isensee F, et al. *Automated brain extraction of multi-sequence MRI using artificial
  neural networks.* Hum Brain Mapp. 2019. doi:10.1002/hbm.24750

## Software

| Component | License |
|---|---|
| [HD-BET](https://github.com/MIC-DKFZ/HD-BET) (code) | Apache-2.0 |
| [nnU-Net](https://github.com/MIC-DKFZ/nnUNet) | Apache-2.0 |
| [astril](https://github.com/Alexander-Ling/astril) | CC BY-NC-SA 4.0 |
| Other Python dependencies (PyTorch, SimpleITK, dcm2niix, ...) | Their own licenses, included with each installed package |
| NVIDIA CUDA / cuDNN base image (`nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`) | NVIDIA's End User License Agreements (see the license files under `/usr/local/cuda*` in the image). Not covered by this repository's CC BY-NC-SA license. |
