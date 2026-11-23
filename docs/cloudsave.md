# Cloud save

INTTI keeps the save on its own backend (`BackendManager`, `https://www.intti-backend.com`), for a signed-in account. It isn't Google Play saved games. Read from the disassembly (v1.12.0: `BackendManager`, `UserData`, `<DownloadUserDataCoroutine>d__48`, `<UploadUserDataCoroutine>d__46`) and checked in memory.

## What is saved
The whole `UserData.data` (a `UserDataObject`): `guid` (the save's id), and the `ints`, `longs`, `strings` and `floats` dictionaries (coins, skins, cases, records, tasks, ...: see memreader.md). `longs["saved_at"]` is the time of the last local save, in Unix ms. The upload is `RuntimeDataToJson` POSTed as JSON. A few keys are device-only (`UserData.*NonCloudValues*`): they're kept when a download replaces the rest.

Locally the save is written by `UserData.Save` → `SaveRuntimeDataToStorage` (debounced, from `UserData.Update`), which nearly every change calls (`ChangeSkinUnlockedCopiesCount`, `ChangeSkinCasesOwned`, `GameEnd`s, ...). While signed in but not yet synced (`BackendManager.dataSynced` false), local saving waits.

## When it syncs
- **Upload** (`UploadUserData`; needs a stored token and no account request running, `accountProcessOn`; the request itself times out after `accountProcessTimeout`, 5 s, and sets no flag):
  - when the app **loses focus** (`OnApplicationFocus(false)`, once it has run over 2 s), at most every **30 s** (`autoSaveOnDefocusCounter`);
  - after a download that kept the local save;
  - after redeeming a promo code.

  Nothing else uploads: no timer, no upload on quitting.
- **Download** (`DownloadUserData`, from `SessionSuccessfullyValidated` when `dataSynced` is false):
  - at start (`Start` → `Invoke` → validating the stored session);
  - on regaining focus after **5 min** away (`now − focusLostAt ≥ 300 000 ms`: `dataSynced` is cleared).

## Who wins: the whole save, last writer
After downloading, the cloud save **replaces the local one** (`SaveNewDataToStorage`, then `SystemSettings.ReloadCurrentScrene`) if any of these holds:
- its `guid` differs from the local one;
- its `saved_at` is more than **60 s** newer than the local `saved_at` (`cloud − local > 59 999`);
- the download was forced.

Otherwise the **local save is uploaded over the cloud one**, and `dataSynced` is set. Nothing is merged key by key, so progress made on one device is lost if another device's save wins:
- Two devices on one account: device A plays and uploads; device B, whose last upload is older, starts, finds the cloud more than 60 s newer and takes A's save. B's progress since its last upload is gone.
- The other way: a device whose local `saved_at` is newer (or within 60 s) uploads over the cloud, and the other device's progress is gone.

## The bots
The bots' Waydroid runs headless and INTTI never loses focus (`focusLostAt` stays 0), so **a whole bot session never uploads**. Force-stopping it (`device.stop_app`, the watchdog's restart) also skips the defocus upload. The cloud then keeps the save from the session's start until INTTI next starts there and finds its local save newer. If the phone plays in between, one side's progress is lost.

So close INTTI with:
```sh
python -m inttibot cloud close     # Home -> the game uploads -> 6 s for the request -> force-stop
python -m inttibot cloud           # the state: synced, account request running, focusLostAt, saved_at
```
`close` presses Home, waits for `focusLostAt` to move (the game took the defocus and started the upload), gives the request 6 s (its timeout is 5 s; nothing in memory shows it finishing), then force-stops. Don't play on another device while a bot session runs on the same account.

Memory: `BackendManager` statics `dataSynced` (+0x10), `forceValidateOnRefocus` (+0x11); instance `accountProcessOn` (+0x20), `autoValidateCounter` (+0x28), `autoSaveOnDefocusCounter` (+0x2c), `focusLostAt` (+0x30, Unix ms).
