#!/usr/bin/env node

const fs = require('fs');
const https = require('https');
const process = require('process');

// Load configuration from file
function loadConfig(filename) {
  try {
    const data = fs.readFileSync(filename, 'utf8');
    const config = JSON.parse(data);

    if (!config.bearerToken) {
      throw new Error('bearer token is empty in config file');
    }

    return config;
  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

// Create a client for making API requests
function createClient(token) {
  return {
    baseURL: 'https://api.sumup.com',
    token: token,
    createRequest(method, path) {
      const url = `${this.baseURL}${path}`;
      const headers = {
        'Authorization': `Bearer ${this.token}`,
        'Content-Type': 'application/json'
      };

      return { url, headers, method };
    }
  };
}

// Wait for specified milliseconds
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Get transaction status
function getTransactionStatus(client, merchantCode, clientTransactionID) {
  return new Promise((resolve, reject) => {
    if (!clientTransactionID.trim()) {
      reject(new Error('client transaction ID cannot be empty'));
      return;
    }

    if (!merchantCode.trim()) {
      reject(new Error('merchant code cannot be empty'));
      return;
    }

    const path = `/v2.1/merchants/${merchantCode}/transactions?client_transaction_id=${clientTransactionID}`;
    const request = client.createRequest('GET', path);

    // Parse URL for https.request
    const urlObj = new URL(request.url);

    const options = {
      method: request.method,
      hostname: urlObj.hostname,
      path: `${urlObj.pathname}${urlObj.search}`,
      headers: request.headers,
      timeout: 10000
    };

    const req = https.request(options, (res) => {
      let responseData = '';

      res.on('data', (chunk) => {
        responseData += chunk;
      });

      res.on('end', () => {
        try {
          if (res.statusCode === 200) {
            const response = JSON.parse(responseData);

            // Check if the response is directly the transaction object
            if (response.status && response.client_transaction_id === clientTransactionID) {
              resolve(response.status);
            }
            // Check if response has items array
            else if (response.items && response.items.length > 0) {
              resolve(response.items[0].status);
            }
            else {
              reject(new Error(`no transaction found with client_transaction_id: ${clientTransactionID}`));
            }
          } else if (res.statusCode === 404) {
            try {
              const apiErr = JSON.parse(responseData);
              reject(new Error(`transaction not found: ${apiErr.message}`));
            } catch (e) {
              reject(new Error(`transaction not found (ID: ${clientTransactionID})`));
            }
          } else {
            try {
              const apiErr = JSON.parse(responseData);
              if (apiErr.message) {
                reject(new Error(`API error (status ${res.statusCode}): ${apiErr.message}`));
              } else {
                reject(new Error(`unexpected response (status ${res.statusCode}): ${res.statusMessage}`));
              }
            } catch (e) {
              reject(new Error(`unexpected response (status ${res.statusCode}): ${res.statusMessage}`));
            }
          }
        } catch (error) {
          reject(new Error(`Error parsing response: ${error.message}`));
        }
      });
    });

    req.on('error', (error) => {
      reject(new Error(`error sending request: ${error.message}`));
    });

    req.end();
  });
}

// Poll for transaction status until SUCCESSFUL, FAILED, or max attempts reached
async function pollTransactionStatus(client, merchantCode, clientTransactionID, maxAttempts = 60, intervalMs = 1000) {
  let attempts = 0;

  while (attempts < maxAttempts) {
    attempts++;

    try {
      const status = await getTransactionStatus(client, config.merchantCode, clientTransactionID);

      if (status === 'SUCCESSFUL' || status === 'FAILED') {
        return status;
      }

      // Wait for the specified interval before trying again
      await sleep(intervalMs);

    } catch (error) {
      // If we get an error, just wait and try again
      await sleep(intervalMs);
    }
  }

  return 'TIMEOUT';
}

// Main function
async function main() {
  if (process.argv.length !== 3) {
    console.error('Error: missing client transaction ID');
    process.exit(1);
  }

  const clientTransactionID = process.argv[2].trim();
  config = loadConfig('config.json');
  const client = createClient(config.bearerToken);

  try {
    const finalStatus = await pollTransactionStatus(client, config.merchantCode, clientTransactionID);
    // Only output the final status, nothing else
    console.log(finalStatus);
  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

// Global config variable
let config;

// Execute main function
main();