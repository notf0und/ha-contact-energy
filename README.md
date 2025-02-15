# **Contact Energy Integration for Home Assistant**  
Easily monitor your **energy usage and account details** directly in Home Assistant.  

## **Installation**  

### **HACS (Recommended)**  
1. Ensure [HACS is installed](https://hacs.xyz/docs/setup/download).  
2. Click the button below to open the repository in HACS:  
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=notf0und&repository=ha-contact-energy&category=integration)  
3. Install the **Contact Energy** integration.  
4. Restart Home Assistant.  

### **Manual Installation**  
1. Download the integration files from the repository.  
2. Copy all files from `custom_components/contact_energy` to your Home Assistant folder `config/custom_components/contact_energy`
4. Restart Home Assistant


## Getting started
1. Open Home Assistant and navigate to:
2. Settings → Devices & Services → + Add Integration
3. Search for Contact Energy and select it.
4. Enter the required details:
 * Email & Password: Use the credentials for your Contact Energy account.
 * Usage Days: Number of days to fetch data from Contact Energy's API (Recommended: 10 days).

Once configured, the integration will begin fetching and displaying your account and usage data.
A prompt will asking for email, password and usage days. 


## Viewing Usage Data and Costs in Home Assistant
To see your electricity usage and costs in Home Assistant’s Energy Dashboard, follow these steps:

1. Go to → Settings → Dashboards → Energy
2. Click "Add Consumption" and select:
  * Contact Energy - Electricity (###)
    * Use an entity tracking the total costs
    * Select Contact Energy - Electricity Cost (###)
3. Click "Add Consumption" again and select:
 * Contact Energy - Free Electricity (###)

Once added, you can now view your energy usage and costs by opening the Energy Dashboard in Home Assistant.

⚠ Important: Contact Energy typically provides data with a 2-3 day delay. If today's date is 15, the latest available data may only go up to the 12th. Make sure to check previous days in the Energy Dashboard to see the latest available data.

## Known issues
Currently, no known issues.

## Future enhancements
Your contributions and feedback are always welcome!

## Special mentions
This integration was originally developed by [@codyc1515](https://github.com/codyc1515)-huge thanks for laying the foundation!
