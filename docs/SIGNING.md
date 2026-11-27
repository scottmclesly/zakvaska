# Code signing

The desktop installers are built unsigned until certificates are added. This
is what signing changes, what it costs, and exactly what to add when you have
it. Nothing in the code needs editing: the release workflow looks for the
secrets below and signs when it finds them.

## What users see without it

- **macOS:** "Apple could not verify Zakvaska…", and a trip to System
  Settings to allow it, once. The README walks through it.
- **Windows:** a blue "Windows protected your PC" box, *More info* →
  *Run anyway*, once.

Signing removes both. Neither is required to publish.

## macOS: Developer ID and notarisation

**Cost:** the Apple Developer Program, about US$99 a year.

1. Enrol at <https://developer.apple.com/programs/>.
2. In Xcode or the developer site, create a **Developer ID Application**
   certificate. Export it from Keychain Access as a `.p12` with a password.
3. At <https://account.apple.com>, create an **app-specific password** for
   notarisation.
4. In the repository on GitHub: *Settings → Secrets and variables → Actions →
   New repository secret*, and add:

| Secret | What it is |
|---|---|
| `APPLE_CERTIFICATE` | the `.p12`, base64-encoded: `base64 -i cert.p12 \| pbcopy` |
| `APPLE_CERTIFICATE_PASSWORD` | the password you exported it with |
| `APPLE_SIGNING_IDENTITY` | the certificate's name, e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` | the Apple ID email you enrolled with |
| `APPLE_PASSWORD` | the app-specific password from step 3 |
| `APPLE_TEAM_ID` | the ten-character team ID from the developer site |

The next tag is signed and notarised.

**Not yet proven.** This path has never run, because there has been no
certificate to run it with. The app carries a frozen Python server, which is
several hundred compiled files, and Apple's notary checks every one. Expect
the first signed build to need attention: most likely an entitlements file
(`com.apple.security.cs.allow-unsigned-executable-memory` and
`com.apple.security.cs.disable-library-validation`, which a bundled Python
usually needs) named in `tauri.conf.json` under `bundle.macOS.entitlements`,
and possibly signing the files under `Contents/Resources/server` explicitly.
Apple's own guidance is that nested programs belong in `Contents/MacOS` or
`Contents/Frameworks` rather than `Resources`, where the server sits today, so
the fix may be to move it. Use "Run workflow" on the Release action to try it without publishing, and
read the notary's log if it refuses.

## Windows

**Cost:** varies; a certificate from a certificate authority is a few hundred
US dollars a year, and Microsoft's own Trusted Signing service is a monthly
subscription with eligibility rules by country and account type. Check current
terms before buying: this is the part most likely to have changed.

If you have a certificate as a `.pfx` file, add:

| Secret | What it is |
|---|---|
| `WINDOWS_CERTIFICATE` | the `.pfx`, base64-encoded |
| `WINDOWS_CERTIFICATE_PASSWORD` | its password |

The workflow imports it and signs the installer and the program inside it.

Most certificates sold today do not come as a file: the key lives on a USB
token or in a cloud service and cannot be exported. For those, and for
Trusted Signing, the workflow's "Windows signing" step needs replacing with
one that calls the provider's signing tool; Tauri supports that through
`bundle.windows.signCommand`. That is a small change, but it depends on the
provider, so it is left until one is chosen.

**Not yet proven**, for the same reason as macOS.

Note that a new certificate does not silence SmartScreen at once: Windows
builds up trust in a publisher as people install the app.
