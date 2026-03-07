"""Quick verification script for FilmDB Query Engine."""
import sys
sys.path.insert(0, "backend")
sys.path.insert(0, ".")

from rag.filmdb_query_engine import FilmDBQueryEngine

engine = FilmDBQueryEngine.get_instance()

# Test 1: Title resolution
print("=== Test 1: Title resolution ===")
for title in ["Inception", "The Dark Knight", "Interstellar", "Parasite"]:
    iid = engine.resolve_title_to_imdb_id(title)
    print("  {} -> {}".format(title, iid))

# Test 2: Entity lookup
print("\n=== Test 2: Entity lookup ===")
entity = engine.entity_lookup("tt1375666")  # Inception
if entity:
    print("  title: {}".format(entity.get("title")))
    print("  year: {}".format(entity.get("year")))
    print("  rating: {}".format(entity.get("imdb_rating")))
    print("  genres: {}".format(entity.get("genres")))
    print("  overview: {}...".format(str(entity.get("overview", ""))[:80]))
    print("  poster_path: {}".format(entity.get("poster_path")))
else:
    print("  FAILED: No entity found")

# Test 3: Plot analysis
print("\n=== Test 3: Plot analysis ===")
plot = engine.plot_analysis("tt1375666")
if plot:
    print("  plot_text length: {}".format(len(str(plot.get("plot_text", "")))))
    print("  plot_text[:80]: {}...".format(str(plot.get("plot_text", ""))[:80]))
else:
    print("  No plot found (expected for some movies)")

# Test 4: Critic summary
print("\n=== Test 4: Critic summary ===")
critic = engine.critic_summary("tt1375666")
if critic:
    print("  review_count: {}".format(critic["review_count"]))
    print("  sentiments: {}".format(critic["sentiment_breakdown"]))
    if critic.get("reviews"):
        r = critic["reviews"][0]
        print("  top review: {} | {}...".format(r.get("critic_name"), str(r.get("review_text", ""))[:60]))
else:
    print("  No reviews found")

# Test 5: Movie similarity
print("\n=== Test 5: Movie similarity ===")
similar = engine.movie_similarity("tt1375666")
if similar:
    recs = similar.get("recommendations", [])
    print("  Found {} similar movies".format(len(recs)))
    for r in recs[:3]:
        print("    {} ({}) - {} shared tags".format(r.get("title"), r.get("year"), r.get("overlap_count")))
else:
    print("  No similarity data")

# Test 6: Top rated
print("\n=== Test 6: Top rated (Action, top 5) ===")
top = engine.top_rated(genre="Action", count=5)
for m in top["movies"]:
    print("  {} ({}) - {}".format(m["title"], m["year"], m["rating"]))

# Test 7: Person filmography
print("\n=== Test 7: Person filmography (Christopher Nolan) ===")
person = engine.person_filmography("Christopher Nolan")
if person:
    print("  name: {}".format(person["name"]))
    print("  professions: {}".format(person["professions"]))
    print("  credit_count: {}".format(person["credit_count"]))
    for f in person["filmography"][:5]:
        print("    {} ({}) - {}".format(f.get("title"), f.get("year"), f.get("category")))
else:
    print("  FAILED: Person not found")

# Test 8: Movie comparison
print("\n=== Test 8: Movie comparison (Inception vs Interstellar) ===")
cmp = engine.compare_movies("tt1375666", "tt0816692")
if cmp:
    a = cmp.get("movie_a", {})
    b = cmp.get("movie_b", {})
    print("  movie_a: {} ({}) - {}".format(a.get("title"), a.get("year"), a.get("imdb_rating")))
    print("  movie_b: {} ({}) - {}".format(b.get("title"), b.get("year"), b.get("imdb_rating")))
else:
    print("  FAILED: Comparison returned None")

print("\n=== All tests completed ===")
