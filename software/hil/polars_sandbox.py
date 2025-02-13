from datetime import datetime, timedelta
import numpy as np
import polars as pl

frame = pl.DataFrame(
    {
        "timestamp": [datetime.now() + timedelta(seconds=i) for i in range(10)],
        "data": list(range(10)),
    }
)


data = (
    frame.sort("timestamp")
    .filter(pl.col("timestamp") >= pl.col("timestamp").max() - timedelta(seconds=3))
    .get_column("data")
    .to_numpy()
)

assert np.all(6 < data) and np.all(data < 10)
