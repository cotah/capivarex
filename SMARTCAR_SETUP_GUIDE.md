# Smartcar Integration Setup Guide

## Overview

The **SuperBot God** now integrates with **Smartcar API** to provide comprehensive electric vehicle management capabilities. This integration allows users to monitor their vehicle's battery level, location, charging status, and remotely control charging and locks—all through conversational AI.

---

## 🚗 Features

### **Monitoring (Unlimited)**
- 🔋 **Battery Level:** Check current battery percentage and remaining range
- 📍 **Location:** Get real-time vehicle GPS coordinates
- 🔌 **Charging Status:** Monitor if vehicle is plugged in and charging state
- 🛣️ **Odometer:** View total distance traveled
- 📊 **Vehicle Info:** Get make, model, year, and VIN

### **Commands (Limited by Plan)**
- 🔒 **Lock/Unlock:** Remotely secure or access your vehicle
- ⚡ **Start/Stop Charging:** Control charging sessions remotely

---

## 📋 Prerequisites

1. **Smartcar Account:** Create a free account at [dashboard.smartcar.com](https://dashboard.smartcar.com/)
2. **Build Plan:** The project uses Smartcar's Build Basic plan ($1.99/vehicle/month)
3. **Compatible Vehicle:** Supports 30+ EV brands (Tesla, BMW, Audi, VW, Nissan, Ford, etc.)

---

## ⚙️ Configuration Steps

### **Step 1: Smartcar Dashboard Setup**

1. Log in to [Smartcar Dashboard](https://dashboard.smartcar.com/)
2. Navigate to **Configuration** → **Redirect URIs**
3. Add the following redirect URI:
   ```
   http://localhost:8000/callback/smartcar
   ```
4. Save the configuration

### **Step 2: Environment Variables**

Your `.env` file should already contain the Smartcar credentials:

```env
# Smartcar API
SMARTCAR_CLIENT_ID=63db1caf-1824-44e6-8c10-ea398a29442b
SMARTCAR_CLIENT_SECRET=8bc61c62-55ec-483f-8527-d8f23fdde0cc
SMARTCAR_MANAGEMENT_TOKEN=dfda94f8-9136-4ec1-afe0-2479a2d1028d
SMARTCAR_REDIRECT_URI=http://localhost:8000/callback/smartcar
```

### **Step 3: Install Dependencies**

The Smartcar Python SDK is already installed. If you need to reinstall:

```bash
pip install smartcar
```

---

## 🔄 OAuth Flow

### **Connecting a Vehicle**

1. **User requests to connect vehicle** via chat:
   ```
   "Conecte meu carro"
   ```

2. **Bot provides Smartcar Connect URL:**
   - User clicks the link
   - Selects their vehicle brand
   - Logs in with manufacturer credentials
   - Authorizes SuperBot God to access vehicle

3. **OAuth Callback:**
   - Smartcar redirects to: `http://localhost:8000/callback/smartcar?code=...&state=user_id`
   - Backend exchanges authorization code for access token
   - Tokens are stored in database (TODO: implement storage)

4. **Vehicle Connected:**
   - User can now query vehicle status and send commands

---

## 💬 Usage Examples

### **Monitoring Queries**

```
"Qual o nível de bateria do meu carro?"
"Onde está meu carro?"
"Meu carro está carregando?"
"Quantos km já rodei?"
"Me dê um resumo do meu veículo"
```

### **Control Commands**

```
"Tranque meu carro"
"Destranque meu carro"
"Inicie o carregamento"
"Pare o carregamento"
```

---

## 🏗️ Architecture

### **Components**

1. **Car Service** (`services/car_service.py`)
   - OAuth flow management
   - Smartcar API communication
   - Token refresh handling
   - Vehicle data retrieval
   - Command execution

2. **Car Agent** (`agents/car_agent.py`)
   - Intent analysis (GPT-4)
   - Natural language processing
   - User-friendly responses
   - Context-aware suggestions

3. **API Routes** (`api/routes/car.py`)
   - REST endpoints for vehicle operations
   - OAuth callback handler
   - Token management

4. **Orchestrator Integration**
   - Added "car" intent to both REST and WebSocket orchestrators
   - Seamless routing of vehicle-related queries

---

## 📊 API Endpoints

### **Connect Vehicle**
```http
POST /api/car/connect
Content-Type: application/json

{
  "user_id": "user_123"
}
```

**Response:**
```json
{
  "success": true,
  "connect_url": "https://connect.smartcar.com/oauth/authorize?...",
  "message": "Redirect user to this URL to connect their vehicle"
}
```

### **OAuth Callback**
```http
GET /callback/smartcar?code=AUTH_CODE&state=user_123
```

**Response:**
```json
{
  "success": true,
  "user_id": "user_123",
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": "2026-02-13T00:00:00Z",
  "vehicle_ids": ["vehicle_id_1"],
  "vehicle_info": {
    "make": "Tesla",
    "model": "Model 3",
    "year": 2023
  }
}
```

### **Query Vehicle**
```http
POST /api/car/query
Content-Type: application/json

{
  "message": "Qual o nível de bateria?",
  "user_id": "user_123",
  "vehicle_id": "vehicle_id_1",
  "access_token": "..."
}
```

### **Get Battery Level**
```http
GET /api/car/battery?vehicle_id=vehicle_id_1&access_token=...
```

### **Lock Vehicle**
```http
POST /api/car/lock?vehicle_id=vehicle_id_1&access_token=...
```

---

## 🧪 Testing

### **Run Integration Tests**

```bash
cd "/home/ubuntu/supergod_final/SUPERGOD MAPS"
python3.11 test_car_integration.py
```

**Expected Output:**
```
✅ ALL TESTS PASSED!

📋 NEXT STEPS:
1. Add Redirect URI to Smartcar Dashboard
2. Test OAuth flow by visiting the connect URL
3. Connect a test vehicle (simulated or real)
```

### **Test with Simulated Vehicle**

1. Change mode in `services/car_service.py`:
   ```python
   mode='simulated'  # Instead of 'live'
   ```

2. Use Smartcar's test vehicles:
   - Username: `user@smartcar.com`
   - Password: `password`

---

## 💰 Cost Management

### **Smartcar Pricing**

- **Build Basic Plan:** $1.99/vehicle/month
- **Commands:** 100 commands/month total (across all vehicles)
- **Monitoring:** Unlimited (battery, location, etc.)

### **Optimization Strategy**

1. **Monitoring is Free:** Encourage users to check status frequently
2. **Commands are Premium:** 
   - Free tier: Monitoring only
   - Basic tier ($2.99/month): 10 commands/month
   - Standard tier ($5.99/month): 30 commands/month
   - Pro tier ($9.99/month): 100 commands/month

3. **Command Tracking:** Implement usage counter in database

---

## 🔒 Security

### **Token Storage**

**TODO:** Implement secure token storage in Supabase:

```sql
CREATE TABLE user_vehicles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id),
  vehicle_id VARCHAR(255) NOT NULL,
  access_token TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  make VARCHAR(100),
  model VARCHAR(100),
  year INTEGER,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### **Token Refresh**

Tokens expire after a certain period. Implement automatic refresh:

```python
# Check if token is expired
if datetime.now() > expires_at:
    # Refresh token
    new_tokens = await car_service.refresh_access_token(refresh_token)
    # Update in database
```

---

## 🌍 Multi-Region Support

### **Supported Regions**

Smartcar supports vehicles in:
- 🇺🇸 United States
- 🇨🇦 Canada
- 🇬🇧 United Kingdom
- 🇩🇪 Germany
- 🇫🇷 France
- 🇮🇪 Ireland (Your location!)
- And more...

### **Vehicle Brands**

30+ brands supported including:
- Tesla
- BMW
- Audi
- Volkswagen
- Nissan
- Ford
- Chevrolet
- Mercedes-Benz
- Porsche
- Jaguar
- Land Rover
- And more...

---

## 🐛 Troubleshooting

### **"Vehicle not connected" message**

**Solution:** User needs to complete OAuth flow first. Bot will provide connect URL.

### **"Failed to get battery level" error**

**Possible causes:**
1. Token expired → Implement token refresh
2. Vehicle doesn't support this feature → Check compatibility
3. Vehicle is offline → Ask user to check vehicle connectivity

### **OAuth callback not working**

**Checklist:**
- ✅ Redirect URI added to Smartcar Dashboard
- ✅ Backend server is running on port 8000
- ✅ Credentials in `.env` are correct
- ✅ User completed authorization on Smartcar Connect

---

## 📚 Resources

- [Smartcar API Documentation](https://smartcar.com/docs/)
- [Smartcar Python SDK](https://github.com/smartcar/python-sdk)
- [Smartcar Dashboard](https://dashboard.smartcar.com/)
- [Supported Vehicles](https://smartcar.com/docs/api-reference/compatibility/)

---

## 🚀 Next Steps

1. **✅ Complete:** Car Service implementation
2. **✅ Complete:** Car Agent integration
3. **✅ Complete:** API routes and orchestration
4. **⏳ Pending:** User adds Redirect URI to Smartcar Dashboard
5. **⏳ Pending:** Implement token storage in Supabase
6. **⏳ Pending:** Test with real vehicle
7. **⏳ Future:** Add command usage tracking
8. **⏳ Future:** Implement proactive notifications (low battery, charging complete)

---

**Author:** Manus AI  
**Date:** February 12, 2026  
**Version:** 1.0
