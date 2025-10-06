## ⚠️ Disclaimer

This project is not affiliated, associated, authorized, endorsed by, or in any way officially connected with Finder S.p.A.
The Finder BLISS name, as well as related names, marks, emblems and images, are registered trademarks of their respective owners.
This integration is provided for **research and interoperability purposes only**.
Use it at your own risk.

# Finder Bliss Thermostats (Home Assistant Custom Component)
This is a Home Assistant custom component that provides sensor and climate entity support for **FINDER BLISS** thermostats (BLISS1, BLISS2) using the unofficial Python API, `pyFinderBliss`.

It allows you to:
* Monitor current temperature, humidity, battery level, and Wi-Fi signal.
* Control the target temperature (setpoint).
* Change the operating mode (HEAT/MANUAL, AUTO, OFF).

**Note:** This integration is unofficial and is not related in any way to Finder. It was developed by reverse-engineering the requests made by the official app, and the API may stop working at any time if the provider makes changes.

---

## 🚀 Installation (via HACS - Recommended)

This integration can be installed easily using the Home Assistant Community Store (HACS).

1.  **Open HACS** in your Home Assistant UI.
2.  Go to the **Integrations** section.
3.  Click the **three dots** in the top right corner and select **Custom repositories**.
4.  Enter the URL of this repository: `https://github.com/condatek/finderBlissHA`
5.  Select the **Category** as `Integration`.
6.  Click **ADD**.
7.  HACS will list the new repository. Search for **"Finder Bliss"** and click **Download**.
8.  **Restart Home Assistant** to ensure the new component is loaded.

## 🛠️ Configuration

After restarting Home Assistant:

1.  Go to **Settings** -> **Devices & Services** -> **Integrations**.
2.  Click **ADD INTEGRATION**.
3.  Search for **"Finder Bliss"**.
4.  Enter your **Finder Bliss App Credentials** (Username/Email and Password).
5.  The integration will validate the credentials, fetch your devices, and create the corresponding `climate` and `sensor` entities.

## 💻 Manual Installation (Not Recommended)

1.  Download the contents of this repository.
2.  Copy the entire `finderblissha` folder into your Home Assistant's `custom_components` directory.
    * *Example Path: `/config/custom_components/finderblissha/`*
3.  Restart Home Assistant.
4.  Follow the configuration steps above (Settings -> Devices & Services -> Add Integration).

---

## 👨‍💻 Contributing

Contributions to this project are welcome! If you'd like to help develop features or improve functionality, please fork the repository and create a pull request.

**TODOs:**
* Optimize the WebSocket connection for real-time updates.
* Add support for specific device features (e.g., specific schedule modes).
* Improve error handling and extend test coverage.