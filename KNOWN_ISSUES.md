# Known Issues

1. `book_session` route does DB table queries before validating store existence

- In `/store/<store_id>/book`, we fetch available/unavailable tables before checking if the store exists.
- This is minor but does unnecessary DB work for invalid `store_id` requests.
- File: `d20/routes/stores.py`
