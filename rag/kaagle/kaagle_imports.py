import kagglehub

def safe_download(dataset_name):
    try:
        path = kagglehub.dataset_download(dataset_name)
        print(f"Path to {dataset_name}: {path}")
        return path
    except Exception as e:
        print(f"Failed to download {dataset_name}: {e}")
        return None

# top 10000 movies
path1 = safe_download("dk123891/10000-movies-data")

# Download latest version
path = kagglehub.dataset_download("diegobartoli/imdbtopfilms")

print("Path to dataset files:", path)

# Streaming services
path3 = safe_download("ruchi798/movies-on-netflix-prime-video-hulu-and-disney")

# TV shows on Netflix, Prime Video, Hulu and Disney
path4 = safe_download("ruchi798/tv-shows-on-netflix-prime-video-hulu-and-disney")


import kagglehub

# Oscar 1927 -2025
path = kagglehub.dataset_download("unanimad/the-oscar-award")

print("Path to dataset files:", path)

# highest grossing movies
path = kagglehub.dataset_download("bidyutchanda/top-10-highest-grossing-films-19752018")

print("Path to dataset files:", path)

# netflix-tv-shows-and-movies-eda has imdb id
path = kagglehub.dataset_download("mohdshoaibalam/netflix-tv-shows-and-movies-eda")

print("Path to dataset files:", path)   