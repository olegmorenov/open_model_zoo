# repvgg-b0

## Use Case and High-Level Description

RepVGG-B0 is image classification model pre-trained on ImageNet dataset. RepVGG is architecture of convolutional neural network, which has a VGG-like inference-time body and structural re-parameterization technique.

The model input is a blob that consists of a single image of "1x3x224x224" in RGB order.

The model output is typical object classifier for the 1000 different classifications matching with those in the ImageNet database.

For details see [repository](https://github.com/DingXiaoH/RepVGG) and [paper](https://arxiv.org/abs/2101.03697).

## Specification

| Metric           | Value          |
| ---------------- | -------------- |
| Type             | Classification |
| GFLOPs           | TBD            |
| MParams          | TBD            |
| Source framework | PyTorch\*      |

## Accuracy

| Metric | Value |
| ------ | ----- |
| Top 1  | 75.16% |
| Top 5  | 92.42% |

## Input

### Original model

Image, name - `input`,  shape - `1, 3, 224, 224`, format is `B, C, H, W` where:

- `B` - batch size
- `C` - channel
- `H` - height
- `W` - width

Channel order is `RGB`.
Mean values - [123.675,116.28,103.53], scale values - [58.395,57.12,57.375].

### Converted model

Image, name - `input`,  shape - `1, 3, 224, 224`, format is `B, C, H, W` where:

- `B` - batch size
- `C` - channel
- `H` - height
- `W` - width

Channel order is `BGR`.

## Output

### Original model

Object classifier according to ImageNet classes, name - `output`,  shape - `1, 1000`, output data format is `B, C` where:

- `B` - batch size
- `C` - predicted probabilities for each class in [0, 1] range

### Converted model

Object classifier according to ImageNet classes, name - `output`,  shape - `1, 1000`, output data format is `B, C` where:

- `B` - batch size
- `C` - predicted probabilities for each class in [0, 1] range

## Legal Information

The original model is released under the following [license](https://raw.githubusercontent.com/DingXiaoH/RepVGG/main/LICENSE):

```
MIT License

Copyright (c) 2020 DingXiaoH

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
