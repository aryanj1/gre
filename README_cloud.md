# GRE Tracker — private family dashboard

This Streamlit app tracks GRE study progress from October 16 to October 29, 2026. Your dad can open it as a **viewer** but only someone who knows your **owner password** can save, delete, or import entries. Each request reads live data from Supabase.

## 1. Set up the database

1. Go to https://supabase.com/dashboard and make a free project.
2. Open **SQL Editor** → **New query**. Paste `supabase_setup.sql` and click **Run**.
3. Copy the Project URL (e.g. `https://abcxyz.supabase.co`) and a **server-side secret key**, prefixed `sb_secret_`, from project **Settings → API Keys**. Do not use the `anon` or `sb_publishable_` key.

## 2. Deploy on Streamlit Community Cloud

1. Create a **private** GitHub repository.
2. Add these files to the root of the repo:
   - `gre_tracker_cloud.py`
   - `requirements.txt`
   - `.gitignore`
3. Go to https://share.streamlit.io → **Create app** and choose the repository. Set main file to `gre_tracker_cloud.py`.
4. Before deploying, or afterward in **App settings → Secrets**, add (replacing the example placeholders):

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_YOUR_SECRET_VALUE"
OWNER_PASSWORD = "A_UNIQUE_LONG_RANDOM_PASSWORD_ONLY_YOU_KNOW"
```

Save secrets and deploy. **Never put actual secrets into GitHub**, screenshots, or chat messages.

## 3. Let your dad view it

1. On your Streamlit app, select **Share** (or App settings → Sharing).
2. Make sure **Only specific people can view this app** (private) is selected.
3. Add your dad's email as a **viewer**, not a GitHub developer.
4. Send him the Streamlit URL. He signs in with Google or an emailed sign-in link.

His dashboard will say **Viewer · read-only**. The chart, targets, progress, and CSV download work normally. You will also enter at first as a viewer; open **Unlock owner editing** in the sidebar and enter your owner password to edit. Lock editing when finished.

**Limitation:** Streamlit's private-app viewer access is separate from the in-app edit password; anyone who learns the edit password AND has access to the private app can edit. Never share the password with viewers. Streamlit viewers can invite additional viewers to your workspace, so the owner should periodically review the viewer list.

## 4. Move existing progress (optional)

1. Open the **original local** `gre_tracker.py` on your Mac and click **Export all data as CSV**.
2. In your **cloud** app, unlock owner editing.
3. Expand **Import previous CSV backup** in the sidebar and upload that CSV.
4. Unsaved days are ignored; dates already saved in the cloud won't be overwritten unless you opt in.

## 5. Run the cloud-connected version on your Mac (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p .streamlit
# Create .streamlit/secrets.toml locally with the same TOML secrets as above.
streamlit run gre_tracker_cloud.py
```

Note: Local and cloud versions using the same Supabase project share exactly the same progress. Your original `gre_tracker.py` continues to use the old local SQLite database; it does not automatically sync.

## Backup and troubleshooting

Use the app's **Export all data as CSV** to keep an extra backup. If the app says the configuration is incomplete, ensure you have all three secrets. If it cannot load data, check the SQL setup, project URL, and secret key. Cloud deployment doesn't transfer existing local `.db` files by itself.
