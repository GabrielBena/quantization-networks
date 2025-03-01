import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.parametrize import register_parametrization as rpm
from quant.quantization import Quantization
import copy


class Net(nn.Module):
    def __init__(self, **kwargs):
        super().__init__()

        self.modules_dict = nn.ModuleDict(
            {
                "conv1": nn.Conv2d(kwargs.get("n_channels", 1), 32, 3, 1),
                "relu1": nn.ReLU(),
                "mp1": nn.MaxPool2d(2),
                "conv2": nn.Conv2d(32, 64, 3, 1),
                "relu2": nn.ReLU(),
                "mp2": nn.MaxPool2d(2),
                "fc1": nn.Linear(kwargs.get("n_flatten", 1600), 128),
                "relu3": nn.ReLU(),
                "fc2": nn.Linear(128, 10),
            }
        )

        self.dropout = kwargs.get("dropout", 0)

    def forward(self, x):

        for name, module in self.modules_dict.items():
            if (
                isinstance(module, nn.Linear)
                or (
                    isinstance(module, nn.Sequential)
                    and isinstance(module[0], nn.Linear)
                )
            ) and len(x.shape) > 2:
                x = x.view(x.size(0), -1)
            x = module(x)
            if self.dropout > 0 and "fc" in name:
                x = F.dropout(x, p=self.dropout, training=self.training)

            # print(name, x.shape, x.unique().shape)

        return x


def compose2(f, g):
    return lambda *a, **kw: f(g(*a, **kw))


class QuantizedModel(nn.Module):

    def __init__(self, model, n_bits=4, quantize_activations=False):
        super().__init__()
        self.quantized = True
        self.model = copy.deepcopy(model)
        self.n_bits = n_bits
        self.quantize_activations = quantize_activations

        for n, m in self.model.named_modules():
            if (
                hasattr(m, "weight")
                and (not "parametrizations" in n)
                and (m.weight.numel() > 1)
            ):
                rpm(m, "weight", Quantization(self.n_bits))
                if quantize_activations:
                    m.quant = Quantization(n_bits)
                    m.original_forward = copy.deepcopy(m.forward)
                    m.forward = compose2(m.quant.forward, m.forward)

    def forward(self, x):
        return self.model(x)

    def set_temperature(self, T):
        for m in self.modules():
            if hasattr(m, "T"):
                m.T = T

    def set_inference(self, inference):
        for m in self.modules():
            if hasattr(m, "inference"):
                m.inference = inference

    @property
    def original_weights(self):
        return {
            n: m.parametrizations.weight.original for n, m in self.modules_dict.items()
        }

    @property
    def modules_dict(self):
        return {n: m for n, m in self.named_modules() if hasattr(m, "parametrizations")}

    @property
    def n_layers(self):
        return len(self.original_weights)
