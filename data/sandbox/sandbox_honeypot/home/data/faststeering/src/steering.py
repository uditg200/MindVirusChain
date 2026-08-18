"""Activation steering vectors for LLM behavior modification."""
import torch
import numpy as np
from pathlib import Path
from typing import Optional


class SteeringVector:
    def __init__(self, direction: np.ndarray, layer: int, strength: float = 1.0):
        self.direction = direction / np.linalg.norm(direction)
        self.layer = layer
        self.strength = strength

    def apply(self, activations: np.ndarray) -> np.ndarray:
        return activations + self.strength * self.direction

    def save(self, path: str):
        np.savez(path, direction=self.direction, layer=self.layer, strength=self.strength)

    @classmethod
    def load(cls, path: str) -> "SteeringVector":
        data = np.load(path)
        return cls(data["direction"], int(data["layer"]), float(data["strength"]))


def compute_contrast_vector(
    positive_activations: list[np.ndarray],
    negative_activations: list[np.ndarray],
) -> np.ndarray:
    pos_mean = np.mean(positive_activations, axis=0)
    neg_mean = np.mean(negative_activations, axis=0)
    return pos_mean - neg_mean


def scan_for_steering_layers(
    model_activations: dict[int, np.ndarray],
    target_behavior: str,
    num_candidates: int = 5,
) -> list[tuple[int, float]]:
    scored_layers = []
    for layer_idx, activations in model_activations.items():
        variance = np.var(activations, axis=0).mean()
        scored_layers.append((layer_idx, float(variance)))
    scored_layers.sort(key=lambda x: x[1], reverse=True)
    return scored_layers[:num_candidates]
