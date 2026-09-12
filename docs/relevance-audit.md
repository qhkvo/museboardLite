# Relevance audit — 2026-09-12

18 supported JPEG/PNG fixtures processed locally with the pinned C++ encoder. Three WebP files excluded (unsupported by the upload/processing pipeline). No live collection or search cutoff changed.

## Same-subject evaluation

Labels inferred from visual inspection: four dog images (16,19,20,21), two cats (17,18), and two chairs (14,15). Same group = relevant; different groups = irrelevant. This is a small development set, not held-out validation.

| Cutoff | Relevant retained / 8 | Unrelated retained / 20 |
|---|---:|---:|
| 0.60 | 7 | 9 |
| 0.65 | 6 | 4 |
| 0.70 | 5 | 2 |
| 0.75 | 2 | 2 |
| 0.80 | 2 | 2 |

## Labeled pair scores

| Source | Candidate | Expected | Cosine similarity |
|---|---|---|---:|
| 17-cmeme1.jpeg | 18-cmeme2.jpeg | Yes | 0.8639 |
| 16-dmeme1.jpeg | 18-cmeme2.jpeg | No | 0.8625 |
| 14-red-chair.jpg | 15-blue-chair.jpg | Yes | 0.8498 |
| 16-dmeme1.jpeg | 17-cmeme1.jpeg | No | 0.8067 |
| 20-dpark.jpg | 21-dog.jpg | Yes | 0.7424 |
| 16-dmeme1.jpeg | 19-dmeme2.jpeg | Yes | 0.7186 |
| 19-dmeme2.jpeg | 20-dpark.jpg | Yes | 0.7028 |
| 18-cmeme2.jpeg | 20-dpark.jpg | No | 0.6897 |
| 16-dmeme1.jpeg | 20-dpark.jpg | Yes | 0.6757 |
| 18-cmeme2.jpeg | 19-dmeme2.jpeg | No | 0.6655 |
| 17-cmeme1.jpeg | 20-dpark.jpg | No | 0.6366 |
| 14-red-chair.jpg | 18-cmeme2.jpeg | No | 0.6365 |
| 14-red-chair.jpg | 17-cmeme1.jpeg | No | 0.6265 |
| 17-cmeme1.jpeg | 19-dmeme2.jpeg | No | 0.6087 |
| 18-cmeme2.jpeg | 21-dog.jpg | No | 0.6033 |
| 19-dmeme2.jpeg | 21-dog.jpg | Yes | 0.6023 |
| 15-blue-chair.jpg | 18-cmeme2.jpeg | No | 0.5986 |
| 14-red-chair.jpg | 16-dmeme1.jpeg | No | 0.5847 |
| 14-red-chair.jpg | 20-dpark.jpg | No | 0.5762 |
| 16-dmeme1.jpeg | 21-dog.jpg | Yes | 0.5616 |
| 15-blue-chair.jpg | 20-dpark.jpg | No | 0.5582 |
| 15-blue-chair.jpg | 17-cmeme1.jpeg | No | 0.5546 |
| 14-red-chair.jpg | 21-dog.jpg | No | 0.5413 |
| 15-blue-chair.jpg | 21-dog.jpg | No | 0.5399 |
| 17-cmeme1.jpeg | 21-dog.jpg | No | 0.5365 |
| 15-blue-chair.jpg | 16-dmeme1.jpeg | No | 0.5365 |
| 14-red-chair.jpg | 19-dmeme2.jpeg | No | 0.4930 |
| 15-blue-chair.jpg | 19-dmeme2.jpeg | No | 0.4780 |

## Nearest images for every source

### 01-portrait.jpeg

- 02-portrait.jpeg: 1.0000
- 10-baboon-texture.jpg: 0.5325
- 18-cmeme2.jpeg: 0.5323
- 09-fruit-saturated.jpg: 0.5257
- 14-red-chair.jpg: 0.5013

### 02-portrait.jpeg

- 01-portrait.jpeg: 1.0000
- 10-baboon-texture.jpg: 0.5325
- 18-cmeme2.jpeg: 0.5323
- 09-fruit-saturated.jpg: 0.5257
- 14-red-chair.jpg: 0.5013

### 03-landscape-mirrored-exif2.jpg

- 13-mountain-large.jpg: 0.5598
- 05-kayaker.png: 0.4831
- 19-dmeme2.jpeg: 0.4720
- 14-red-chair.jpg: 0.4550
- 11-sudoku-neutral.png: 0.4544

### 05-kayaker.png

- 06-park-runner.png: 0.5933
- 20-dpark.jpg: 0.5485
- 21-dog.jpg: 0.5373
- 13-mountain-large.jpg: 0.5354
- 14-red-chair.jpg: 0.5232

### 06-park-runner.png

- 05-kayaker.png: 0.5933
- 20-dpark.jpg: 0.5630
- 13-mountain-large.jpg: 0.5306
- 09-fruit-saturated.jpg: 0.5267
- 12-basketball.png: 0.5139

### 09-fruit-saturated.jpg

- 15-blue-chair.jpg: 0.6109
- 10-baboon-texture.jpg: 0.6075
- 14-red-chair.jpg: 0.5929
- 20-dpark.jpg: 0.5822
- 18-cmeme2.jpeg: 0.5803

### 10-baboon-texture.jpg

- 18-cmeme2.jpeg: 0.6241
- 09-fruit-saturated.jpg: 0.6075
- 17-cmeme1.jpeg: 0.5767
- 14-red-chair.jpg: 0.5745
- 15-blue-chair.jpg: 0.5679

### 11-sudoku-neutral.png

- 12-basketball.png: 0.5722
- 18-cmeme2.jpeg: 0.5720
- 14-red-chair.jpg: 0.5607
- 17-cmeme1.jpeg: 0.5387
- 16-dmeme1.jpeg: 0.5333

### 12-basketball.png

- 17-cmeme1.jpeg: 0.6351
- 18-cmeme2.jpeg: 0.6263
- 20-dpark.jpg: 0.5887
- 16-dmeme1.jpeg: 0.5858
- 11-sudoku-neutral.png: 0.5722

### 13-mountain-large.jpg

- 03-landscape-mirrored-exif2.jpg: 0.5598
- 09-fruit-saturated.jpg: 0.5454
- 05-kayaker.png: 0.5354
- 06-park-runner.png: 0.5306
- 10-baboon-texture.jpg: 0.5147

### 14-red-chair.jpg

- 15-blue-chair.jpg: 0.8498
- 18-cmeme2.jpeg: 0.6365
- 17-cmeme1.jpeg: 0.6265
- 09-fruit-saturated.jpg: 0.5929
- 16-dmeme1.jpeg: 0.5847

### 15-blue-chair.jpg

- 14-red-chair.jpg: 0.8498
- 09-fruit-saturated.jpg: 0.6109
- 18-cmeme2.jpeg: 0.5986
- 10-baboon-texture.jpg: 0.5679
- 20-dpark.jpg: 0.5582

### 16-dmeme1.jpeg

- 18-cmeme2.jpeg: 0.8625
- 17-cmeme1.jpeg: 0.8067
- 19-dmeme2.jpeg: 0.7186
- 20-dpark.jpg: 0.6757
- 12-basketball.png: 0.5858

### 17-cmeme1.jpeg

- 18-cmeme2.jpeg: 0.8639
- 16-dmeme1.jpeg: 0.8067
- 20-dpark.jpg: 0.6366
- 12-basketball.png: 0.6351
- 14-red-chair.jpg: 0.6265

### 18-cmeme2.jpeg

- 17-cmeme1.jpeg: 0.8639
- 16-dmeme1.jpeg: 0.8625
- 20-dpark.jpg: 0.6897
- 19-dmeme2.jpeg: 0.6655
- 14-red-chair.jpg: 0.6365

### 19-dmeme2.jpeg

- 16-dmeme1.jpeg: 0.7186
- 20-dpark.jpg: 0.7028
- 18-cmeme2.jpeg: 0.6655
- 17-cmeme1.jpeg: 0.6087
- 21-dog.jpg: 0.6023

### 20-dpark.jpg

- 21-dog.jpg: 0.7424
- 19-dmeme2.jpeg: 0.7028
- 18-cmeme2.jpeg: 0.6897
- 16-dmeme1.jpeg: 0.6757
- 17-cmeme1.jpeg: 0.6366

### 21-dog.jpg

- 20-dpark.jpg: 0.7424
- 18-cmeme2.jpeg: 0.6033
- 19-dmeme2.jpeg: 0.6023
- 16-dmeme1.jpeg: 0.5616
- 14-red-chair.jpg: 0.5413

## Pipeline verification and conclusion

Ran scripts/verify_reference.py on all 18 successful results. Model checksum,
512-dimensional normalized output, and independent Pillow/Python ONNX preprocessing
checks passed. Minimum C++/reference cosine was 0.99999613 and maximum absolute
component error was 0.000521894. This verifies integration with the pinned ONNX
export, not parity with original PyTorch weights or subject recognition quality.

The 0.75 cutoff retains only 2/8 labeled same-subject pairs (cats and chairs),
and misses all six dog pairs. It also retains two dog/cat mismatches. Lowering
it to 0.70 retains 5/8 positive pairs, but does not eliminate those mismatches.
No single cutoff can include all dog pairs while rejecting all dog/cat pairs.

Do not present cosine scores as subject confidence. For a same-subject product
requirement, evaluate explicit subject tags/classification or a different retrieval
model on these labeled pairs plus a separate held-out set. Keep embedding search
as visual similarity with adjustable strictness. No production behavior changed.
