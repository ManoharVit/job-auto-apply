from utils import is_excluded_title
import yaml

with open("config.yaml") as f:
    config = yaml.safe_load(f)

title = "Sr. Software Engineer | Defence"
exc = config["filters"]["excluded_title_keywords"]
print(f"Title: {title}")
print(f"Excluded: {exc}")
print(f"Result: {is_excluded_title(title, exc)}")

title2 = "Principal Software Engineer"
print(f"Title 2: {title2}")
print(f"Result 2: {is_excluded_title(title2, exc)}")
