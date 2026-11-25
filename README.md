# CivicSense AI - Civic Issue Reporting System

An AI-powered platform that allows citizens to report civic issues 
(potholes, garbage, broken streetlights, etc.) via photo upload. The 
system automatically classifies the issue, estimates severity, detects
duplicate reports, assigns priority, and routes it to the correct 
municipal department.

## Features
- 📸 Image-based AI issue classification (10 categories)
- ⚡ Automated severity & priority scoring
- 🏛️ Auto-routing to relevant government department
- 🔁 Duplicate detection using geolocation
- 👍 Community upvoting to boost priority
- 💬 Citizen feedback form with an admin inbox
- 📊 Public dashboard with live charts
- 🔐 Admin panel for status management
- 📍 Tracking ID system for citizens

## Setup

```bash
pip install -r requirements.txt
python app.py
```