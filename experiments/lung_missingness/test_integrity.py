"""Check outcome safety, patient identity and fold-local preprocessing invariance."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from models import Preprocessor, cox_loss
from prepare import outcome, patient_id


class IntegrityTests(unittest.TestCase):
    def test_unknown_death_is_not_censoring(self):
        self.assertIsNotNone(outcome({"demographic": {"vital_status": "Dead"}, "diagnoses": [{"days_to_last_follow_up": 200}]})[3])
        self.assertIsNotNone(outcome({"demographic": {"vital_status": "Not Reported"}, "follow_ups": [{"days_to_follow_up": 800}]})[3])

    def test_observed_status_and_time(self):
        self.assertEqual(outcome({"demographic": {"vital_status": "Dead", "days_to_death": 100}})[:2], (True, 100.0))
        self.assertEqual(outcome({"demographic": {"vital_status": "Alive"}, "diagnoses": [{"days_to_last_follow_up": 10}], "follow_ups": [{"days_to_follow_up": 900}]})[:2], (False, 900.0))
        self.assertIsNotNone(outcome({"demographic": {"vital_status": "Alive", "days_to_death": 100}})[3])

    def test_patient_not_slide_id(self):
        self.assertEqual(patient_id("TCGA-05-4244-01Z-00-DX1.h5"), "TCGA-05-4244")
        self.assertEqual(patient_id("C3L-00001-21.h5"), "C3L-00001")

    def test_breslow_tied_risk_sets(self):
        r = torch.zeros(3, requires_grad=True)
        loss = cox_loss(r, torch.tensor([True, True, False]), torch.tensor([1., 1., 3.]))
        self.assertAlmostEqual(float(loss.detach()), float(np.log(3)), places=6)
        loss.backward()
        self.assertTrue(torch.isfinite(r.grad).all())

    def test_heldout_features_do_not_change_training_transform(self):
        root = Path(__file__).parent / "prepared"
        z = np.load(root / "features.npz", allow_pickle=False)
        a = {k: z[k].copy() for k in ["clinical", "wsi", "rna"]}
        columns = json.loads((root / "summary.json").read_text())["clinical_columns"]
        train = np.arange(60)
        p = Preprocessor().fit(a, columns, train)
        original, _ = p.transform(a)
        for key in a:
            a[key][60:] = 100000
        changed = Preprocessor().fit(a, columns, train)
        new, _ = changed.transform(a)
        for old, now in zip(original, new):
            np.testing.assert_allclose(old[:60], now[:60], atol=1e-5)

    def test_unique_ids_and_no_outcome_columns(self):
        root = Path(__file__).parent / "prepared"
        c = pd.read_csv(root / "cohort.csv")
        self.assertTrue(c.patient_id.is_unique)
        self.assertTrue(c.time_days.gt(0).all())
        columns = json.loads((root / "summary.json").read_text())["clinical_columns"]
        self.assertFalse(any(any(s in x for s in ["death", "vital_status", "follow", "survival", "treatment"]) for x in columns))


if __name__ == "__main__":
    unittest.main()
