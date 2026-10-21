import pandas as pd

from wesad_phase1.constants import REST
from wesad_phase1.facts import add_facts


def test_rest_relative_facts():
    df = pd.DataFrame(
        {
            "subject_id": ["S2"] * 4,
            "y": [REST, REST, 1, 1],
            "HR_mean": [70.0, 72.0, 95.0, 98.0],
            "RMSSD": [40.0, 38.0, 20.0, 18.0],
            "EDA_mean": [0.4, 0.42, 1.1, 1.2],
            "TEMP_mean": [32.5, 32.5, 32.3, 32.2],
            "ACC_energy": [1.0, 1.05, 1.02, 0.98],
        }
    )
    out = add_facts(df)
    stress = out[out["y"] == 1].iloc[0]
    assert stress["HR_INCREASED"]
    assert stress["HRV_DECREASED"]
    assert stress["EDA_ACTIVATED"]
    assert stress["ACTIVITY_LOW"]
    assert stress["stress_rule_hit"]
