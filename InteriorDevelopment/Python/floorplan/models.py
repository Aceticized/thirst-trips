"""The two neural networks. Both are downloaded from Hugging Face the first time they are used.

Any estimator with these two methods works, so tests and the demo plug in fakes:

    depth.predict(image, frame)      -> float32 array (height, width): metres along the viewing direction
    segmenter.predict(image, frame)  -> int array (height, width): a label id per pixel
    segmenter.label_ids(names)       -> set of label ids whose name starts with one of `names`
"""

import numpy as np
from PIL import Image


def _pick_device(requested: str) -> str:
    import torch

    if requested != "auto":
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


class DepthEstimator:
    """Metric depth from one photo (Depth Anything V2, indoor version: the numbers are metres)."""

    def __init__(self, model_name: str, device: str = "auto"):
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        self.model_name = model_name
        self.device = _pick_device(device)
        self._torch = torch
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = AutoModelForDepthEstimation.from_pretrained(model_name).to(self.device).eval()

    def predict(self, image: Image.Image, frame=None) -> np.ndarray:
        torch = self._torch
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            predicted = self.model(**inputs).predicted_depth          # (1, h, w)
        resized = torch.nn.functional.interpolate(
            predicted.unsqueeze(1), size=(image.height, image.width), mode="bicubic", align_corners=False
        )
        return resized.squeeze().float().cpu().numpy().astype(np.float32)


class SemanticSegmenter:
    """Wall / floor / ceiling / door ... per pixel (Mask2Former trained on ADE20K)."""

    def __init__(self, model_name: str, device: str = "auto"):
        import torch
        from transformers import AutoImageProcessor, Mask2FormerForUniversalSegmentation

        self.model_name = model_name
        self.device = _pick_device(device)
        self._torch = torch
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = Mask2FormerForUniversalSegmentation.from_pretrained(model_name).to(self.device).eval()
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}

    def predict(self, image: Image.Image, frame=None) -> np.ndarray:
        torch = self._torch
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        labels = self.processor.post_process_semantic_segmentation(outputs, target_sizes=[(image.height, image.width)])[0]
        return labels.cpu().numpy().astype(np.int32)

    def label_ids(self, names) -> set[int]:
        return label_ids_from(self.id2label, names)


def label_ids_from(id2label: dict[int, str], names) -> set[int]:
    """ADE20K names look like "floor, flooring" or "windowpane, window"; match on the first word."""
    wanted = {name.lower() for name in names}
    return {i for i, label in id2label.items() if label.split(",")[0].strip().lower() in wanted}
