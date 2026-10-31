"""
AI Classifier Module for Civic Sense Reporting System
------------------------------------------------------
This module simulates an AI-powered image classification system.
It uses OpenCV-based feature extraction + a RandomForest classifier.
In production, replace with a trained CNN (e.g., MobileNetV2/ResNet
fine-tuned on civic issue datasets).
"""

import cv2
import numpy as np
import os
import random
from sklearn.ensemble import RandomForestClassifier
import joblib

CATEGORIES = [
    'pothole', 'garbage', 'streetlight', 'water_leakage',
    'graffiti', 'broken_sidewalk', 'illegal_dumping',
    'drainage', 'traffic_signal', 'other'
]

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'civic_model.pkl')


class CivicAIClassifier:
    def __init__(self):
        self.model = None
        self._load_or_train_model()

    def _extract_features(self, image_path):
        """Extract handcrafted visual features from image."""
        img = cv2.imread(image_path)
        if img is None:
            return np.zeros(15)

        img = cv2.resize(img, (128, 128))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Color histogram features (captures dominant colors)
        hist_b = cv2.calcHist([img], [0], None, [8], [0, 256]).flatten()
        hist_g = cv2.calcHist([img], [1], None, [8], [0, 256]).flatten()
        hist_r = cv2.calcHist([img], [2], None, [8], [0, 256]).flatten()

        # Edge density (potholes/cracks have high edge density)
        edges = cv2.Canny(gray, 100, 200)
        edge_density = np.sum(edges > 0) / edges.size

        # Texture - standard deviation (rough surfaces = high variance)
        texture_std = np.std(gray)

        # Dark region ratio (potholes/water leakage tend to be dark)
        dark_ratio = np.sum(gray < 60) / gray.size

        # Green/brown ratio for garbage/organic waste detection
        lower_green = np.array([25, 40, 40])
        upper_green = np.array([90, 255, 255])
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        green_ratio = np.sum(green_mask > 0) / green_mask.size

        features = np.concatenate([
            hist_b / (hist_b.sum() + 1e-6),
            [edge_density, texture_std / 255.0, dark_ratio, green_ratio]
        ])
        return features[:15] if len(features) >= 15 else np.pad(features, (0, 15 - len(features)))

    def _load_or_train_model(self):
        if os.path.exists(MODEL_PATH):
            self.model = joblib.load(MODEL_PATH)
        else:
            self.model = self._bootstrap_model()
            joblib.dump(self.model, MODEL_PATH)

    def _bootstrap_model(self):
        """
        Bootstraps a baseline RandomForest with synthetic feature
        distributions representative of each category. This allows
        the system to work out-of-the-box; it should be replaced
        with real training data (self.train()) for production use.
        """
        X, y = [], []
        rng = np.random.default_rng(42)

        profiles = {
            'pothole':        {'edge': 0.35, 'dark': 0.4,  'green': 0.02, 'texture': 0.5},
            'garbage':        {'edge': 0.25, 'dark': 0.15, 'green': 0.3,  'texture': 0.6},
            'streetlight':    {'edge': 0.15, 'dark': 0.5,  'green': 0.05, 'texture': 0.3},
            'water_leakage':  {'edge': 0.1,  'dark': 0.3,  'green': 0.05, 'texture': 0.2},
            'graffiti':       {'edge': 0.4,  'dark': 0.1,  'green': 0.02, 'texture': 0.55},
            'broken_sidewalk':{'edge': 0.3,  'dark': 0.2,  'green': 0.05, 'texture': 0.45},
            'illegal_dumping':{'edge': 0.28, 'dark': 0.2,  'green': 0.25, 'texture': 0.5},
            'drainage':       {'edge': 0.2,  'dark': 0.45, 'green': 0.1,  'texture': 0.35},
            'traffic_signal': {'edge': 0.3,  'dark': 0.2,  'green': 0.05, 'texture': 0.4},
            'other':          {'edge': 0.2,  'dark': 0.2,  'green': 0.15, 'texture': 0.4},
        }

        for cat, p in profiles.items():
            for _ in range(60):
                hist = rng.dirichlet(np.ones(8))
                edge = np.clip(rng.normal(p['edge'], 0.05), 0, 1)
                texture = np.clip(rng.normal(p['texture'], 0.05), 0, 1)
                dark = np.clip(rng.normal(p['dark'], 0.05), 0, 1)
                green = np.clip(rng.normal(p['green'], 0.05), 0, 1)
                feat = np.concatenate([hist, [edge, texture, dark, green]])
                feat = feat[:15] if len(feat) >= 15 else np.pad(feat, (0, 15 - len(feat)))
                X.append(feat)
                y.append(cat)

        clf = RandomForestClassifier(n_estimators=150, max_depth=10, random_state=42)
        clf.fit(X, y)
        return clf

    def predict(self, image_path):
        """Predict category and confidence for an uploaded image."""
        features = self._extract_features(image_path).reshape(1, -1)
        probs = self.model.predict_proba(features)[0]
        classes = self.model.classes_
        best_idx = np.argmax(probs)
        category = classes[best_idx]
        confidence = round(float(probs[best_idx]) * 100, 2)
        return category, confidence

    def analyze_severity(self, image_path):
        """
        Analyze image to estimate severity (0-100) based on
        visual cues like size of damaged area, darkness, edge density.
        """
        img = cv2.imread(image_path)
        if img is None:
            return 30.0

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        edge_density = np.sum(edges > 0) / edges.size
        dark_ratio = np.sum(gray < 60) / gray.size
        texture_variance = np.std(gray) / 255.0

        # Weighted severity formula
        severity = (edge_density * 45) + (dark_ratio * 35) + (texture_variance * 20)
        severity = min(100, max(10, severity * 100))
        return round(severity, 2)

    def train(self, image_label_pairs):
        """
        Real training function: pass list of (image_path, label) tuples
        collected from verified reports, to continuously improve the model.
        """
        X, y = [], []
        for path, label in image_label_pairs:
            X.append(self._extract_features(path))
            y.append(label)
        clf = RandomForestClassifier(n_estimators=150, max_depth=10, random_state=42)
        clf.fit(X, y)
        self.model = clf
        joblib.dump(self.model, MODEL_PATH)


# Singleton instance used across the app
classifier = CivicAIClassifier()