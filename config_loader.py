import json

def load_config(filename):
    try:
        with open(filename, 'r') as file:
            config = json.load(file)
            if not config.get('bearerToken'):
                raise ValueError('bearer token is empty in config file')
            return config
    except Exception as e:
        print(f"Error reading config file: {str(e)}")
        exit(1)