# Known Issues

1. Slider constraint is not covered by browser-level tests
- We validate invalid time ranges on the backend and have route tests, but we do not have a browser/UI test that asserts the `noUiSlider` `margin: 1` behavior directly.
- File: `d20/templates/stores/book_session.html`

2. `book_session` route does DB table queries before validating store existence
- In `/store/<store_id>/book`, we fetch available/unavailable tables before checking if the store exists.
- This is minor but does unnecessary DB work for invalid `store_id` requests.
- File: `d20/routes/stores.py`
