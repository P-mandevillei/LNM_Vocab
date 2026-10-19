# Google accounts and Firebase setup

The app uses **Google account sign-in through Streamlit OIDC** and **Firebase
Cloud Firestore Standard edition** for saved tests. Firebase Authentication,
Gmail API access, Firebase Hosting and a Firebase browser API key are not needed.
Users can keep practicing as guests while account setup is unfinished.
Google login uses [Streamlit's OIDC support](https://docs.streamlit.io/develop/api-reference/user/st.login).

## 1. Identify the deployed app URL

Find your app at <https://share.streamlit.io>. Copy its public URL, such as
`https://your-latin-app.streamlit.app`. The Google callback is that exact URL
followed by `/oauth2callback`. Do not use a GitHub repository URL.

You can send the public app URL and Firebase project ID in chat. **Do not send
client secrets, service-account JSON contents, private keys or secrets.toml.**

## 2. Create Firestore

1. Open <https://console.firebase.google.com> and create a dedicated project for this app.
   Google Analytics is optional for this app.
2. In **Build → Firestore Database**, create the **Standard edition** database
   with database ID **`(default)`**. Choose a region near the app/users and start
   in **production mode**. The app creates its collections when a first test is saved.
3. In Firestore's **Rules** editor, publish the contents of the repository's
   `firestore.rules`. The rule denies direct browser/mobile access. The server
   SDK authenticates through IAM and the app checks ownership on every access.
   See [Firestore's server-client security model](https://firebase.google.com/docs/firestore/security/rules-conditions).
4. In **Indexes → Single field**, add exemptions for collection ID `attempts`,
   fields `payload`, `source_attempt_ids` and `files`, disabling their indexes.
   Keep the automatic index for `completed_at` enabled. No composite index is needed.

If you already use the Firebase CLI, deploy the checked-in rules/index settings
with `firebase deploy --only "firestore:rules,firestore:indexes" --project YOUR_PROJECT_ID`.
Use the console steps instead if the CLI is not installed.
If reusing a project that serves other apps, merge its existing rules and index
configuration carefully instead of replacing them with this app's files.

## 3. Create a server credential

1. Open <https://console.cloud.google.com/iam-admin/serviceaccounts> with the
   **same project** selected.
2. Choose **Create service account**, name it `latin-vocab-streamlit`, and grant
   the **Cloud Datastore User** role (`roles/datastore.user`). This is the app's
   database credential; it does not need Owner or Editor.
3. Open that service account, then **Keys → Add key → Create new key → JSON**.
4. Save the downloaded file as
   **`.streamlit/private/service-account.json`** inside this repository.
   That directory is ignored by Git. Do not put credentials in chapter files.

If key creation is prohibited by your organization's policy, stop here and say
so; do not change organization policies just to finish this setup.

## 4. Create Google login credentials

1. In the same Google Cloud project, open **Google Auth platform** at
   <https://console.cloud.google.com/auth/overview> and complete its initial setup.
2. Configure the app name/support email in **Branding**. Use an **External**
   audience for personal Google/Gmail accounts. While the app is in testing,
   add your Gmail address under **Audience → Test users**.
3. In **Clients**, create an OAuth client with application type **Web application**.
4. Add the exact deployed callback as an **Authorized redirect URI**, for example:
   `https://your-latin-app.streamlit.app/oauth2callback`.
   For optional local testing also add `http://localhost:8501/oauth2callback`.
5. Download the client JSON after saving the callback and put it at
   **`.streamlit/private/oauth-client.json`**.

When ready to allow users beyond your listed test users, publish the OAuth app
to production through **Audience** in Google Auth platform.

The app requests only `openid profile email`. These identify the Google account;
they do not give the app access to Gmail messages or Google Drive.

## 5. Provide credentials securely and configure the app

After the two files are in `.streamlit/private/`, tell Codex that they are ready
and provide **only the public Streamlit app URL**. Codex can build the local
configuration without printing the credentials. Alternatively, run this yourself
from the repository root, substituting your real public URL:

```powershell
.\.venv\Scripts\python.exe quiz/configure_accounts.py --oauth .streamlit/private/oauth-client.json --service-account .streamlit/private/service-account.json --app-url https://your-latin-app.streamlit.app
```

The helper generates a random cookie secret and writes the ignored
**`.streamlit/secrets.toml`**. It refuses to overwrite an existing secrets file.
The checked-in `.streamlit/secrets.example.toml` shows the configuration shape
without containing real credentials. Keep the generated cookie secret stable
between deployments; replacing it signs users out.

For **Streamlit Community Cloud**:

1. Deploy/push the app changes to the app's selected branch, with
   `quiz/streamlit_app.py` as the main file.
2. Open your app's **Settings → Secrets** editor. Paste the contents of the
   generated `secrets.toml` there, then save and reboot the app.
3. Do not commit the real secrets file or downloaded JSON files. Only the app's
   Secrets editor should receive their contents.

For a local test, generate a separate secrets file using
`--app-url http://localhost:8501` and an appropriate `--output` destination;
install `requirements.txt` and use the localhost callback registered above.
Streamlit reads `.streamlit/secrets.toml` relative to the working directory.

## 6. Verify live behavior

1. Open the deployed app directly in a browser (not an embedded iframe).
2. Sign in with Google, complete one vocabulary test and one morphology test,
   and confirm both say **Saved to your account**.
3. Open **Account**. Verify scores, individual test details, **Retest every entry**,
   **Retest wrong entries**, and both recent-mistake practice buttons.
4. Sign out and sign in again to verify persistence. Use a second Google account
   to verify that it sees only its own history.

If a save fails, the completed record stays queued in that browser session and
has a retry button; it is not marked saved until Firestore confirms it. Download
the test record before closing a session with unsaved results. Authentication
starts a new Streamlit session, so sign in before starting a test.
Submit answers before switching between Practice and Account: Streamlit forms
buffer responses until submission. Practice settings are preserved between pages.

## Data and recent-history behavior

Attempts live at `latin_accounts/{opaque_google_identity}/attempts/{attempt_id}`.
The account ID comes from Google's stable subject identifier, not an email.
Submitted answer text and expanded answer tables are not stored. Each attempt
contains a gzip-compressed version 2 record plus scores/date/type/chapter metadata.
Attempt creation is idempotent, so retrying a save cannot create duplicate scores.

The dashboard defaults to the latest **10 completed tests**; users can choose
5, 10, 20 or 50. Accuracy summaries use total correct answers divided by total
answers, rather than averaging percentages from differently sized tests.
Vocabulary accuracy counts vocabulary answers; morphology accuracy counts cells.

Cumulative practice takes the union of wrong question variants in that window,
even if an entry was answered correctly later. Identical variants are tested
once. Different directions, parsing choices, genders, verb configurations and
noun/adjective pairs remain distinct. Vocabulary and morphology are practiced
separately. New attempts are saved as new tests, with links to their source tests.

Original chapter files must remain installed and immutable. Restoration uses
current morphology data and overrides. Histories do not archive answer keys.
