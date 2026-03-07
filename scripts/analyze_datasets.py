import csv, os, sys

def analyze_csv(name, path, encoding='utf-8', max_sample=5):
    print(f"=== {name} ===", flush=True)
    try:
        size_bytes = os.path.getsize(path)
        size_mb = size_bytes / (1024*1024)
        with open(path, encoding=encoding, errors='replace') as f:
            reader = csv.reader(f)
            header = next(reader)
            count = 0
            samples = []
            for row in reader:
                count += 1
                if count <= max_sample:
                    samples.append(row)
        print(f"  Size: {size_mb:.2f} MB ({size_bytes:,} bytes)")
        print(f"  Num Columns: {len(header)}")
        print(f"  Columns: {header}")
        print(f"  Row count: {count:,}")
        print(f"  Sample rows (first {max_sample}):")
        for r in samples:
            print(f"    {r[:10]}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print(flush=True)

def analyze_tsv(name, path, encoding='utf-8', max_sample=5):
    print(f"=== {name} ===", flush=True)
    try:
        size_bytes = os.path.getsize(path)
        size_mb = size_bytes / (1024*1024)
        with open(path, encoding=encoding, errors='replace') as f:
            reader = csv.reader(f, delimiter='\t')
            header = next(reader)
            count = 0
            samples = []
            for row in reader:
                count += 1
                if count <= max_sample:
                    samples.append(row)
        print(f"  Size: {size_mb:.2f} MB ({size_bytes:,} bytes)")
        print(f"  Num Columns: {len(header)}")
        print(f"  Columns: {header}")
        print(f"  Row count: {count:,}")
        print(f"  Sample rows (first {max_sample}):")
        for r in samples:
            print(f"    {r[:10]}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print(flush=True)

# Indian Movies
analyze_csv("Indian Movies (indian movies.csv)", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\indian movies\indian movies.csv")

# GroupLens ml-32m
analyze_csv("GroupLens/movies.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\grouplens\ml-32m\movies.csv")
analyze_csv("GroupLens/links.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\grouplens\ml-32m\links.csv")
analyze_csv("GroupLens/tags.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\grouplens\ml-32m\tags.csv")

# Rotten Tomatoes
analyze_csv("Rotten Tomatoes/rotten_tomatoes_movies.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\rotten_tomato_film_review\rotten_tomatoes_movies.csv")

# Wikipedia
analyze_csv("Wikipedia/wiki_movie_plots_deduped.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\wikipedia_movie_plot\wiki_movie_plots_deduped.csv")

# TMDB small files
analyze_csv("TMDB/keywords.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\the_movie_data_set_tmdb\keywords.csv")
analyze_csv("TMDB/links.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\the_movie_data_set_tmdb\links.csv")
analyze_csv("TMDB/links_small.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\the_movie_data_set_tmdb\links_small.csv")
analyze_csv("TMDB/movies_metadata.csv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\the_movie_data_set_tmdb\movies_metadata.csv")

print("=== IMDb TSV Files (headers + row count from line count) ===", flush=True)

tsv_files = [
    ("IMDb/name.basics.tsv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\IMDb\name.basics.tsv\name.basics.tsv"),
    ("IMDb/title.basics.tsv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\IMDb\title.basics.tsv\title.basics.tsv"),
    ("IMDb/title.akas.tsv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\IMDb\title.akas.tsv\title.akas.tsv"),
    ("IMDb/title.crew.tsv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\IMDb\title.crew.tsv\title.crew.tsv"),
    ("IMDb/title.episode.tsv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\IMDb\title.episode.tsv\title.episode.tsv"),
    ("IMDb/title.principals.tsv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\IMDb\title.principals.tsv\title.principals.tsv"),
    ("IMDb/title.ratings.tsv", r"D:\Evolve_Robot_Lab\Project\FilmDB_Demo\kb\IMDb\title.ratings.tsv\title.ratings.tsv"),
]

for name, path in tsv_files:
    analyze_tsv(name, path, max_sample=5)

print("DONE", flush=True)
