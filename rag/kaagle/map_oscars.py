import pandas as pd
import os
import kagglehub

# the-oscar-award dataset downlaod cached path
path = kagglehub.dataset_download("unanimad/the-oscar-award")
CSV_FILE = os.path.join(path, "the_oscar_award.csv")

MOVIE_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\movie_entity.parquet"
PERSON_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\person_index.parquet"
OSCAR_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\oscar_layer.parquet"

print("Loading datasets...")
df_oscar = pd.read_csv(CSV_FILE)
df_movie = pd.read_parquet(MOVIE_PARQUET)
df_person = pd.read_parquet(PERSON_PARQUET)

print(f"Loaded {len(df_oscar)} Oscar nominations.")

# Clean up merging keys
def clean_str(s):
    if pd.isna(s): return ""
    return str(s).strip().lower()

df_oscar['clean_film'] = df_oscar['film'].apply(clean_str)
df_movie['clean_title'] = df_movie['title'].apply(clean_str)

df_oscar['clean_name'] = df_oscar['name'].apply(clean_str)

# Pre-process person names properly. Note that person_index has names array in json sometimes, but let's check schema.
# Actually `person_index.parquet` has `name` and `nconst`.
df_person['clean_name'] = df_person['name'].apply(clean_str)

# 1. Map to movie (imdb_id)
# Join on clean_film == clean_title. Because many movies have the same name, year matching is ideal.
# But Oscars happen the year AFTER the film release often. Oscar dataset has 'year_film'
print("Mapping to Movie IDs...")
df_oscar['year_film_str'] = df_oscar['year_film'].astype(str)
df_movie['year_str'] = df_movie['year'].astype(str).str.strip().str[:4]

movie_map = df_movie[['clean_title', 'year_str', 'imdb_id']].drop_duplicates(subset=['clean_title', 'year_str'])

df_oscar = pd.merge(
    df_oscar, 
    movie_map.rename(columns={'clean_title': 'clean_film', 'year_str': 'year_film_str'}),
    on=['clean_film', 'year_film_str'], 
    how='left'
)

# Wait, sometimes movies are released a year prior to year_film. 
# Let's try matching those still missing an imdb_id without year, keeping the most popular.
missing_movie_mask = df_oscar['imdb_id'].isna() & df_oscar['clean_film'].astype(bool)
if missing_movie_mask.any():
    print(f"Missing absolute match for {missing_movie_mask.sum()} entries. Attempting title-only fuzzy map (prioritizing top movies).")
    movie_fallback = df_movie.sort_values(['is_top_movie', 'imdb_votes'], ascending=[False, False]).drop_duplicates(subset=['clean_title'])
    fallback_map = movie_fallback.set_index('clean_title')['imdb_id'].to_dict()
    
    df_oscar.loc[missing_movie_mask, 'imdb_id'] = df_oscar.loc[missing_movie_mask, 'clean_film'].map(fallback_map)

# 2. Map to Person (nconst)
print("Mapping to Person IDs...")
person_map = df_person[['clean_name', 'nconst']].drop_duplicates(subset=['clean_name'])
df_oscar = pd.merge(
    df_oscar,
    person_map.rename(columns={'clean_name': 'clean_name'}),
    on='clean_name',
    how='left'
)

# 3. Clean up and structure the ultimate parquet
print("Finalizing Oscar layer...")
cols_to_keep = [
    'year_film', 'year_ceremony', 'ceremony', 'category', 'canon_category', 
    'name', 'film', 'winner', 'imdb_id', 'nconst'
]
final_oscar = df_oscar[cols_to_keep].copy()

# rename to standard conventions
final_oscar.rename(columns={
    'name': 'nominee_name',
    'film': 'film_title'
}, inplace=True)

# Save
final_oscar.to_parquet(OSCAR_PARQUET, index=False)

print(f"Successfully mapped and saved {len(final_oscar)} Oscar rows to {OSCAR_PARQUET}")
print(f"Movie Matches: {final_oscar['imdb_id'].notna().sum()}")
print(f"Person Matches: {final_oscar['nconst'].notna().sum()}")
