import time
import requests

class PaymentService:
    def __init__(self, config):
        self.config = config

    def create_checkout(self):
        url = f"https://api.sumup.com/v0.1/merchants/{self.config['merchantCode']}/readers/{self.config['readerID']}/checkout"
        headers = {
            'Authorization': f"Bearer {self.config['bearerToken']}",
            'Content-Type': 'application/json'
        }
        data = {
            "total_amount": {
                "currency": self.config['payment']['currency'],
                "minor_unit": self.config['payment']['minorUnit'],
                "value": self.config['payment']['value']
            }
        }
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            response_data = response.json()
            if response.status_code in [200, 201] and 'data' in response_data and 'client_transaction_id' in response_data['data']:
                return response_data['data']['client_transaction_id']
            else:
                return None
        except Exception as e:
            print(f"Error creating checkout: {str(e)}")
            return None

    def get_transaction_status(self, client_transaction_id):
        if not client_transaction_id.strip():
            raise ValueError("client transaction ID cannot be empty")
        url = f"https://api.sumup.com/v2.1/merchants/{self.config['merchantCode']}/transactions"
        params = {'client_transaction_id': client_transaction_id}
        headers = {
            'Authorization': f"Bearer {self.config['bearerToken']}",
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'status' in data and data.get('client_transaction_id') == client_transaction_id:
                return data['status']
            elif 'items' in data and len(data['items']) > 0:
                return data['items'][0]['status']
            else:
                raise ValueError(f"no transaction found with client_transaction_id: {client_transaction_id}")
        elif response.status_code == 404:
            raise ValueError(f"transaction not found (ID: {client_transaction_id})")
        else:
            raise ValueError(f"unexpected response (status {response.status_code}): {response.reason}")

    def poll_transaction_status(self, client_transaction_id, max_attempts=60, interval_ms=1000):
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            try:
                status = self.get_transaction_status(client_transaction_id)
                if status in ["SUCCESSFUL", "FAILED"]:
                    return status
                time.sleep(interval_ms / 1000)
            except Exception as e:
                print(f"Error polling status (attempt {attempts}): {str(e)}")
                time.sleep(interval_ms / 1000)
        return "FAILED"