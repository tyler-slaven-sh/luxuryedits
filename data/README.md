# Bag catalog

Enter purse data in `bags.csv`. Keep the header row as:

```csv
id,name,price,brand,edit,tier,image_name
```

Example row:

```csv
london-001,Mayfair Top Handle,1500.00,Example House,london,Rare,mayfair-top-handle.webp
```

- `id` must be unique and may contain letters, numbers, hyphens, and underscores.
- `price` is entered in USD. The generated JSON stores it as integer cents, so `1500.00` becomes `150000`.
- `image_name` is only the filename. Upload that file to `images/`; the JSON automatically adds `./images/` to its `image` value.
- Image filenames cannot contain spaces or folders and must end in `.avif`, `.jpeg`, `.jpg`, `.png`, or `.webp`.
- Names containing commas can be quoted using normal CSV syntax, such as `"Classic Bag, Small"`.
- `edit` should be `london`, `new-york`, `milan`, or `paris`. Values such as `London Edit` and `New York Edit` are also normalized correctly by the page.

The page loads `bags.json` when it starts. If an Edit has CSV records, those records replace that Edit's built-in demo purses. An empty or unavailable JSON file leaves the demo purses in place.

Because the CSV does not contain a probability column, odds are derived from `tier` and normalized to exactly 100% within each Edit. The editable weights are near the top of the script in `index.html`:

| Tier | Weight |
| --- | ---: |
| Essential | 35 |
| Signature | 21.5 |
| Rare | 12 |
| Exceptional | 7 |
| One of one | 3 |

Unknown tier names receive a default weight of 10.

Run the converter locally from the repository root with:

```sh
bash scripts/csv-to-json.sh
```

On GitHub, `.github/workflows/build-bag-data.yml` runs whenever `data/bags.csv` changes. It overwrites `data/bags.json` and commits the generated file back to the same branch.
