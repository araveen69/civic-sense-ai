import os
import tempfile
import unittest
from unittest.mock import patch

import cv2
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from models import ai_classifier


class AIClassifierTests(unittest.TestCase):
    def test_rebuilds_saved_model_with_incompatible_feature_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = os.path.join(temp_dir, 'civic_model.pkl')
            stale_model = RandomForestClassifier(n_estimators=1, random_state=0)
            stale_model.fit(np.zeros((2, 28)), [0, 1])
            joblib.dump(stale_model, model_path)

            classifier = ai_classifier.CivicAIClassifier.__new__(
                ai_classifier.CivicAIClassifier
            )
            with patch.object(ai_classifier, 'MODEL_PATH', model_path):
                classifier._load_or_train_model()

                self.assertEqual(
                    classifier.model.n_features_in_,
                    ai_classifier.FEATURE_COUNT
                )
                self.assertEqual(
                    joblib.load(model_path).n_features_in_,
                    ai_classifier.FEATURE_COUNT
                )

                image_path = os.path.join(temp_dir, 'sample.png')
                cv2.imwrite(image_path, np.zeros((24, 24, 3), dtype=np.uint8))
                category, confidence = classifier.predict(image_path)
                self.assertIn(category, ai_classifier.CATEGORIES)
                self.assertGreaterEqual(confidence, 0)


if __name__ == '__main__':
    unittest.main()
