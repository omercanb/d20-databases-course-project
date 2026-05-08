# Known Issues

## Checkout and Resource Availability

1. Early checkout does not release the original booking slot.

- When a session is checked out, only `Session.checkout_status` changes to `checked_out`.
- Table and game availability queries still look at overlapping `Session` rows and `SessionGameCopy` rows.
- Result: a table/game booked for `10:00-12:00` remains unavailable for that original range even if checkout happens earlier.

2. Past sessions can remain `active`.

- A session only changes from `active` to `checked_out` during checkout.
- Once `end_time` passes, it no longer blocks new non-overlapping bookings because overlap checks use `start_time < requested_end_time` and `end_time > requested_start_time`.
- Result: old un-checked-out sessions may stay `active` in the database.

3. Checked-out future sessions can still count toward reservation limits.

- Reservation counting checks whether `day + end_time` is still in the future.
- It does not filter out `checkout_status = 'checked_out'`.
- Result: a checked-out session may still count as an upcoming reservation until its original end time passes.

4. Early checkout billing uses booked duration.

- Table fee and session loyalty points are calculated from `end_time - start_time`.
- There is no stored actual checkout time.
- Result: early checkout still charges and awards points for the full booked duration.

5. Already-booked future sessions are not protected if their assigned game copy becomes damaged.

- `SessionGameCopy` stores the exact physical copy assigned at booking time.
- If a later session already booked copy #1 while it was good, and an earlier session then checks out with copy #1 marked `damaged` or `missing_pieces`, the future session still points to copy #1.
- The damaged copy becomes unavailable for new bookings, but existing future bookings are not reassigned, cancelled, or flagged.
- Result: a customer may arrive for a future session whose selected game copy is no longer usable.
- Additional risk: checkout for that future session may see the copy's current damaged condition and charge the wrong customer unless staff corrects it manually.

1. Deleting a voucher template deletes customer-owned vouchers.

- `CustomerVoucher.voucher_id` references `LoyaltyVoucher(id) ON DELETE CASCADE`.
- Store owners can delete `LoyaltyVoucher` rows from voucher management.
- Result: deleting a voucher definition can remove already-purchased customer vouchers.
- Fix direction: prevent deletion when customer vouchers exist, soft-delete/deactivate voucher templates, or snapshot voucher terms into `CustomerVoucher`.
