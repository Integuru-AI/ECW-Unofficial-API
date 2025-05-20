# **ECW Unofficial API**
This project integrates with **eClinicalWorks (ECW)** to manage patient credentials, facilities, providers, appointments, medical history, and various clinical notes. It allows users to create, update, and retrieve medical records and related information efficiently from the ECW platform.

---

## **Endpoints**

### **Authentication & Credentials**
-   **POST** `/add-credentials` – Add and Authorize ECW Credentials

### **Platform Configuration & Lookups**
-   **GET** `/facilities` – Get Facilities List
-   **GET** `/providers` – Get Providers List
-   **GET** `/allergies` – Search Allergies

### **Appointments**
-   **GET** `/get-appointments` – Get Appointments List
-   **POST** `/create-appointment` – Create Appointment
-   **POST** `/update-appointment` – Update Appointment

### **Patient Clinical Data**
-   **GET** `/get-patients` – Get Patients List
-   **GET** `/progress_notes` – Fetch Progress Notes for an Encounter
-   **POST** `/add-surg-hosp-items` – Add Surgical and Hospitalization History Items
-   **POST** `/add-family-history-notes` – Add Family History Notes
-   **POST** `/add-social-history-notes` – Add Social History Notes
-   **POST** `/add-med-hx-allergies` – Add/Update Medical History Text and Allergies

---

## **Installation**
This API is designed to be integrated into a [larger project](https://github.com/Unofficial-APIs/Integrations). For detailed setup, refer to the main integration package documentation.

---

## **Info**
This unofficial API for eClinicalWorks (ECW) is built by **[Integuru.ai](https://integuru.ai/)**. We take custom requests for new platforms or additional features for existing platforms. We also offer hosting and authentication services.

If you have requests or want to work with us, reach out at **richard@taiki.online**.

Here's a **[complete list](https://github.com/Integuru-AI/APIs-by-Integuru)** of unofficial APIs built by Integuru.ai.
This repo is part of our integrations package: **[GitHub Repo](https://github.com/Integuru-AI/Integrations)**.
