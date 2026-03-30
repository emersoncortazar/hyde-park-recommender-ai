import pandas as pd
import numpy as np

data = pd.read_csv('data/data.csv', dtype={28: 'string', 66: 'string'}, low_memory=False)
data.columns = data.columns.str.lower().str.strip()

# Take a stratified-ish sample
sample = data.sample(500, random_state=42)
sample.to_csv('data/sample_500.csv', index=False)
print(f"Shape: {data.shape}")
print(f"Columns: {list(data.columns)}")