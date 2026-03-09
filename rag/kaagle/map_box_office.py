import pandas as pd
import os
import kagglehub

print("Downloading dataset...")
path = kagglehub.dataset_download("bidyutchanda/top-10-highest-grossing-films-19752018")
csv_file = os.path.join(path, "blockbusters.csv")

MOVIE_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\movie_entity.parquet"
METADATA_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\metadata_layer.parquet"

df_gross = pd.read_csv(csv_file)
df_movie = pd.read_parquet(MOVIE_PARQUET)
df_meta = pd.read_parquet(METADATA_PARQUET)

print(f"Loaded {len(df_gross)} blockbuster rows")

def clean_str(s):
    if pd.isna(s): return ""
    return str(s).strip().lower()

df_gross['clean_title'] = df_gross['title'].apply(clean_str)
df_movie['clean_title'] = df_movie['title'].apply(clean_str)

df_gross['year_str'] = df_gross['year'].astype(str)
df_movie['year_str'] = df_movie['year'].astype(str).str.strip().str[:4]

# Map to IMDb IDs
movie_map = df_movie[['clean_title', 'year_str', 'imdb_id']].drop_duplicates(subset=['clean_title', 'year_str'])

df_gross = pd.merge(
    df_gross,
    movie_map,
    on=['clean_title', 'year_str'],
    how='left'
)

# Clean worldwide_gross
df_gross['worldwide_gross'] = df_gross['worldwide_gross'].str.replace('$', '').str.replace(',', '')
df_gross['worldwide_gross'] = pd.to_numeric(df_gross['worldwide_gross'], errors='coerce')

# Map to metadata layer.
# Right now metadata.parquet has "revenue" from tmdb, but this kaggle dataset verified box office is likely more accurate
# for top blockbusters.
df_gross_mapped = df_gross.dropna(subset=['imdb_id']).copy()

# Add to metadata layer
print("Mapping to Metadata Layer...")
gross_map = df_gross_mapped.set_index('imdb_id')

if 'historical_box_office_rank' not in df_meta.columns:
    df_meta['historical_box_office_rank'] = None
if 'historical_worldwide_gross' not in df_meta.columns:
    df_meta['historical_worldwide_gross'] = None
if 'studio' not in df_meta.columns:
    df_meta['studio'] = None

count = 0
for imdb_id, row in gross_map.iterrows():
    mask = df_meta['imdb_id'] == imdb_id
    if mask.any():
        df_meta.loc[mask, 'historical_box_office_rank'] = str(row['rank_in_year'])
        df_meta.loc[mask, 'historical_worldwide_gross'] = row['worldwide_gross']
        df_meta.loc[mask, 'studio'] = row['studio']
        count += 1

print(f"Injected historical box office data into {count} metadata rows.")

df_meta.to_parquet(METADATA_PARQUET, index=False)
print("Saved metadata_layer.parquet")
