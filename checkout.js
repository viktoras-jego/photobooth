#!/usr/bin/env node

const fs = require('fs');
const https = require('https');

// Load configuration from file
function loadConfig(filename) {
  try {
    const data = fs.readFileSync(filename, 'utf8');
    return JSON.parse(data);
  } catch (error) {
    console.error(`Error reading config file: ${error.message}`);
    process.exit(1);
  }
}

// Create checkout via API
function createCheckout(config) {
  return new Promise((resolve, reject) => {
    const { merchantCode, readerID, bearerToken, payment } = config;
    
    const body = JSON.stringify({
      total_amount: {
        currency: payment.currency,
        minor_unit: payment.minorUnit,
        value: payment.value
      }
    });
    
    const options = {
      method: 'POST',
      hostname: 'api.sumup.com',
      path: `/v0.1/merchants/${merchantCode}/readers/${readerID}/checkout`,
      headers: {
        'Authorization': `Bearer ${bearerToken}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      },
      timeout: 10000
    };
    
    const req = https.request(options, (res) => {
      let responseData = '';
      
      res.on('data', (chunk) => {
        responseData += chunk;
      });
      
      res.on('end', () => {
        try {
          const response = JSON.parse(responseData);
          resolve(response);
        } catch (error) {
          reject(new Error(`Error parsing response: ${error.message}`));
        }
      });
    });
    
    req.on('error', (error) => {
      reject(new Error(`Error making request: ${error.message}`));
    });
    
    req.write(body);
    req.end();
  });
}

// Main function
async function main() {
  const config = loadConfig('config.json');
  
  try {
    const response = await createCheckout(config);
    
    if (response?.data?.client_transaction_id) {
      console.log(`Response: ${response.data.client_transaction_id}`);
    } else {
      console.error('Error: No client transaction ID in response');
    }
  } catch (error) {
    console.error(`Error: ${error.message}`);
  }
}

// Execute main function
main();
