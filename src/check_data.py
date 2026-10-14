"""Sanity-check the dataset and compute the baseline you must beat on Day 2."""
from pathlib import Path
import pandas as pd

df = pd.read_parquet(Path(__file__).resolve().parents[1] / "data" / "processed" / "results.parquet")
fin = df.dropna(subset=["finish_pos", "grid"])

print("Rows per season:\n", df.groupby("season").size().to_string())
print("\nDNF rate:", round(df["dnf"].mean() * 100, 1), "%")
print("Rain races:", int(df.groupby(["season", "round"])["rain"].max().sum()))
print("\nBASELINE (finish = grid position)")
print("  MAE of position:", round((fin["grid"] - fin["finish_pos"]).abs().mean(), 3))
print("  Winner = pole hit rate:",
      round((fin[fin.finish_pos == 1]["grid"] == 1).mean() * 100, 1), "%")
