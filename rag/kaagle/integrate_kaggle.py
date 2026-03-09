import pandas as pd
import os
import re

DATA_CSV = r"C:\Users\Naren Kumar\.cache\kagglehub\datasets\dk123891\10000-movies-data\versions\1\data.csv"
MOVIE_PARQUET = r"d:\Evolve_Robot_Lab\Project\FilmDB_Demo\rag\processed_dataset\movie_entity.parquet"

print("Loading datasets...")
df_kaggle = pd.read_csv(DATA_CSV)
df_local = pd.read_parquet(MOVIE_PARQUET)

print(f"Original local rows: {len(df_local)}")

def clean_title(title):
    if pd.isna(title): return ""
    return str(title).strip().lower()

def clean_year(year):
    if pd.isna(year): return ""
    m = re.search(r'(\d{4})', str(year))
    if m: return m.group(1)
    return ""

def clean_votes(v):
    if pd.isna(v): return 0
    return int(str(v).replace(',', ''))

df_kaggle['clean_title'] = df_kaggle['Movie Name'].apply(clean_title)
df_kaggle['clean_year'] = df_kaggle['Year of Release'].apply(clean_year)
df_kaggle['numeric_votes'] = df_kaggle['Votes'].apply(clean_votes)
df_kaggle['numeric_rating'] = pd.to_numeric(df_kaggle['Movie Rating'], errors='coerce')

# Drop duplicates in Kaggle to avoid explosion
df_kaggle = df_kaggle.sort_values('numeric_votes', ascending=False).drop_duplicates(subset=['clean_title', 'clean_year'])

df_local['clean_title'] = df_local['title'].apply(clean_title)
df_local['clean_year'] = df_local['year'].astype(str).str.strip()

# Create a mapping dataframe
map_df = df_kaggle[['clean_title', 'clean_year', 'numeric_rating', 'numeric_votes']].copy()
map_df.rename(columns={'numeric_rating': 'kaggle_rating', 'numeric_votes': 'kaggle_votes'}, inplace=True)

# Merge
df_merged = pd.merge(df_local, map_df, on=['clean_title', 'clean_year'], how='left')

# Update ratings and votes where mapped
mask = df_merged['kaggle_rating'].notna()
print(f"Mapped and updating {mask.sum()} movies...")

df_merged.loc[mask, 'imdb_rating'] = df_merged.loc[mask, 'kaggle_rating']
df_merged.loc[mask, 'imdb_votes'] = df_merged.loc[mask, 'kaggle_votes']

# Flag top movies
df_merged['is_top_movie'] = False
df_merged.loc[mask, 'is_top_movie'] = True

# Drop temporary columns
df_merged.drop(columns=['clean_title', 'clean_year', 'kaggle_rating', 'kaggle_votes'], inplace=True)

# Important: ensure imdb_votes are numbers
df_merged['imdb_votes'] = pd.to_numeric(df_merged['imdb_votes'], errors='coerce').fillna(0)
df_merged['imdb_rating'] = pd.to_numeric(df_merged['imdb_rating'], errors='coerce')

# Save back to parquet
print("Saving updated movie_entity.parquet...")
df_merged.to_parquet(MOVIE_PARQUET, index=False)
print("Done!")
