# Investigating Red Packet Fraud in Android Applications: Insights from User Reviews

## About
This repository stores the tool code and dataset for the paper "Investigating Red Packet Fraud in Android Applications: Insights from User Reviews".
ReckDetector is the approach we proposed in this paper for automatically identifying and collecting apps with red packets from android app markets. 

## Datasets
In this study, we collected 344 apps with red packets from Google Play and three popular alternative Android app markets, including Tencent Market, Huawei Market, and Xiaomi Market.
We crawled over 360,000 real user reviews for the 344 apps with red packets.
Through keyword filtering, a total of 14,875 user reviews related to red packets were obtained.

## Prerequisite

1. `Python 3` 
2. `Android SDK`
3. `Android device` equipped with `Magisk` and `LSPosed` frameworks


## How to use

1. Connect an Android device to your host machine via `adb`.

2. Install the Hook module (`hooking_module/DialogHook.apk`) on the Android device.

3. Configure the parameters of the Hook module, such as the host's IP address and the packages of target apps to be hooked.

4. Execute `loader_batch.py` file to dynamically explore apps and identify red packets.


**Notice**
1. The `DetectReck/input` directory stores `.apk` files of the apps you want to detect.
2. The `DetectReck/output` directory outputs the UTGs of all apps and the list of apps containing red packet.

## Acknowledgement

1. [ReckDroid](https://github.com/FraudDetector/ReckDroid)
2. [Droidbot](https://github.com/honeynet/droidbot)