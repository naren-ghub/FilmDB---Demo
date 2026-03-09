import pandas as pd
import json

datasets = {
    "10000_movies": r"C:\Users\Naren Kumar\.cache\kagglehub\datasets\dk123891\10000-movies-data\versions\1\data.csv",
    "movies_on_streaming": r"C:\Users\Naren Kumar\.cache\kagglehub\datasets\ruchi798\movies-on-netflix-prime-video-hulu-and-disney\versions\5\MoviesOnStreamingPlatforms.csv",
    "tv_shows_on_streaming": r"C:\Users\Naren Kumar\.cache\kagglehub\datasets\ruchi798\tv-shows-on-netflix-prime-video-hulu-and-disney\versions\3\tv_shows.csv"
}

output = {}

for name, path in datasets.items():
    try:
        df = pd.read_csv(path, nrows=5)
        df_full = pd.read_csv(path)
        
        info = {
            "rows": len(df_full),
            "columns": list(df.columns),
            "sample_data": df.fillna("").to_dict(orient="records"),
            "null_counts": df_full.isnull().sum().to_dict()
        }
        output[name] = info
    except Exception as e:
        output[name] = {"error": str(e)}

with open("dataset_analysis.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)

print("Analysis complete. Saved to dataset_analysis.json")
