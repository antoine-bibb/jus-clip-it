# Admin Setup Guide

## Making a User an Admin

To grant a user unlimited uploads, run the admin setup script:

```bash
python make_admin.py user@example.com
```

Replace `user@example.com` with the email of the user you want to make an admin.

## Admin Features

- **Unlimited uploads**: Admins can create unlimited clips without consuming credits
- **No quota restrictions**: Admins bypass all quota limits
- **Visual indicator**: Admin accounts show "(ADMIN)" in the account button

## Database Changes

The `users` table now includes an `is_admin` column (INTEGER, default 0).

## API Changes

The `/api/auth/me` and login endpoints now return `is_admin: true/false` in the response.