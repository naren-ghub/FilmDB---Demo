import pandas as pd
import os
import re

MOVIES_CSV = r"C:\Users\Naren Kumar\.cache\kagglehub\datasets\ruchi798\movies-on-netflix-prime-video-hulu-and-disney\versions\5\MoviesOnStreamingPlatforms.csv"
TV_CSV = r"C:\Users\Naren Kumar\.cache\kagglehub\datasets\ruchi798\tv-shows-on-netflix-prime-video-hulu-and-disney\versions\3\tv_shows.csv"
MOVIE_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\movie_entity.parquet"
STREAMING_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\streaming_layer.parquet"

print("Loading datasets...")
df_movies = pd.read_csv(MOVIES_CSV)
df_tv = pd.read_csv(TV_CSV)
df_local = pd.read_parquet(MOVIE_PARQUET)

def clean_title(title):
    if pd.isna(title): return ""
    return str(title).strip().lower()

def clean_year(year):
    if pd.isna(year): return ""
    m = re.search(r'(\d{4})', str(year))
    if m: return m.group(1)
    return ""

print("Processing streaming datasets...")
df_movies['clean_title'] = df_movies['Title'].apply(clean_title)
df_movies['clean_year'] = df_movies['Year'].apply(clean_year)
df_movies['is_tv_show'] = 0

df_tv['clean_title'] = df_tv['Title'].apply(clean_title)
df_tv['clean_year'] = df_tv['Year'].apply(clean_year)
df_tv['is_tv_show'] = 1

# Extract key columns we want. Note: TV set has 'IMDb' instead of 'Rotten Tomatoes' as a primary stat sometimes, but both have Title, Year, Age, Netflix, Hulu, Prime Video, Disney+
cols_to_keep = ['clean_title', 'clean_year', 'Age', 'Netflix', 'Hulu', 'Prime Video', 'Disney+', 'is_tv_show']

df_combined = pd.concat([
    df_movies[cols_to_keep].dropna(subset=['clean_title']), 
    df_tv[cols_to_keep].dropna(subset=['clean_title'])
], ignore_index=True)

df_combined.drop_duplicates(subset=['clean_title', 'clean_year'], inplace=True)

df_local['clean_title'] = df_local['title'].apply(clean_title)
df_local['clean_year'] = df_local['year'].astype(str).str.strip()

print(f"Combined streaming catalog size: {len(df_combined)}")

# Map to existing imdb_ids where possible
mapped_df = pd.merge(df_combined, df_local[['imdb_id', 'clean_title', 'clean_year']], 
                     on=['clean_title', 'clean_year'], how='left')

mapped_count = mapped_df['imdb_id'].notna().sum()
unmapped_count = mapped_df['imdb_id'].isna().sum()

print(f"Mapped to existing FilmDB IDs: {mapped_count}")
print(f"Unmapped (Mostly TV Shows/New Entities): {unmapped_count}")

# For unmapped entities (like TV shows), we will generate synthetic IDs starting with 'tv_' or 'st_' so they can exist in the same ecosystem.
import uuid
def generate_synthetic_id(row):
    if pd.isna(row['imdb_id']):
        prefix = 'tv_' if row['is_tv_show'] == 1 else 'st_'
        return f"{prefix}{str(uuid.uuid4())[:12]}"
    return row['imdb_id']

mapped_df['imdb_id'] = mapped_df.apply(generate_synthetic_id, axis=1)

# Keep the final columns needed for the streaming layer
final_layer = mapped_df[['imdb_id', 'Age', 'Netflix', 'Hulu', 'Prime Video', 'Disney+', 'is_tv_show', 'clean_title', 'clean_year']].copy()
final_layer.rename(columns={'Prime Video': 'Prime_Video', 'Disney+': 'Disney_Plus'}, inplace=True)

final_layer.to_parquet(STREAMING_PARQUET, index=False)
print(f"Saved streaming layer to {STREAMING_PARQUET} with {len(final_layer)} rows.")

# Next, we must inject the synthetic IDs (unmapped TV shows/streaming movies) into the main movie_entity.parquet so the engine can resolve their titles!
unmapped_movies = mapped_df[mapped_df['imdb_id'].str.startswith('tv_') | mapped_df['imdb_id'].str.startswith('st_')].copy()

if not unmapped_movies.empty:
    print(f"Injecting {len(unmapped_movies)} TV Shows/Streaming Titles into main entity map...")
    new_entities = pd.DataFrame({
        'imdb_id': unmapped_movies['imdb_id'],
        'title': unmapped_movies['clean_title'].str.title(),
        'year': unmapped_movies['clean_year'],
        'type': unmapped_movies['is_tv_show'].map({1: 'tv_show', 0: 'movie'}),
        'is_top_movie': False
    })
    
    # Append to existing movie_entity
    df_local.drop(columns=['clean_title', 'clean_year'], inplace=True, errors='ignore')
    
    # Clean up any previously injected synthetic data to avoid duplicates
    df_local = df_local[~df_local['imdb_id'].astype(str).str.startswith(('tv_', 'st_'), na=False)]

    for col in df_local.columns:
        if col not in new_entities.columns:
            new_entities[col] = None
            
    for col in new_entities.columns:
        if col not in df_local.columns:
            df_local[col] = None
            
    df_extended = pd.concat([df_local, new_entities], ignore_index=True)
    df_extended.to_parquet(MOVIE_PARQUET, index=False)
    print("Main entity map updated with TV/Streaming titles.")
