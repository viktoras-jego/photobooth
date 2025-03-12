import time
import requests
import logging

logger = logging.getLogger('PaymentService')
logger.setLevel(logging.INFO)

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
                logger.info("Checkout created successfully")
                return response_data['data']['client_transaction_id']
            else:
                logger.error(f"Failed to create checkout. Status: {response.status_code}, Response: {response_data}")
                return None
        except Exception as e:
            logger.error(f"Error creating checkout: {str(e)}")
            return None

    def get_transaction_status(self, client_transaction_id):
        if not client_transaction_id.strip():
            logger.error("Client transaction ID cannot be empty")
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
                error_msg = f"No transaction found with client_transaction_id: {client_transaction_id}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        elif response.status_code == 404:
            error_msg = f"Transaction not found (ID: {client_transaction_id})"
            logger.error(error_msg)
            raise ValueError(error_msg)
        else:
            error_msg = f"Unexpected response (status {response.status_code}): {response.reason}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def poll_transaction_status(self, client_transaction_id, max_attempts=60, interval_ms=1000):
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            try:
                status = self.get_transaction_status(client_transaction_id)
                if status in ["SUCCESSFUL", "FAILED"]:
                    logger.info(f"Final transaction status: {status}")
                    return status
                time.sleep(interval_ms / 1000)
            except Exception as e:
                logger.error(f"Error polling status (attempt {attempts}): {str(e)}")
                time.sleep(interval_ms / 1000)
        logger.error("Transaction polling reached maximum attempts")
        return "FAILED"