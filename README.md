# Conversational AI System


## Prerequisites

Before you begin, ensure you have met the following requirements:

* You have installed Python 3.8 or above.
* You have installed pip and pipenv.
* You have installed Redis server.
* You are using a Linux or Mac OS machine. (If you're on Windows, make sure to adapt the commands accordingly.)

## First Time Setup/Installation

## Using Pipenv

```
# Install dependencies
pipenv install

# Create a virtual environment
pipenv shell

# Initialize the database
flask --app app.web init-db

```
## Configuration

1. Make sure to create a `.env` file in the project directory with the necessary environment variables as per the `.env` example shown below:

# Environment Configuration

Before running the application, you need to set up the following environment variables in your `.env` file. Replace `<placeholder>` with your actual secret keys and values.

```bash
# General settings
SECRET_KEY=<your-secret-key> # Secret key for your application to use for session signing
SQLALCHEMY_DATABASE_URI=sqlite:///sqlite.db # Database connection URI

# Service URLs
UPLOAD_URL=https://<your-upload-service-url> # URL to the service where files are uploaded

# OpenAI configurations
OPENAI_API_KEY=<your-openai-api-key> # API key for OpenAI services

# Redis configurations
REDIS_URI=redis://localhost:6379 # URI for Redis server

# Pinecone configurations
PINECONE_API_KEY=<your-pinecone-api-key> # API key for Pinecone services
PINECONE_ENV_NAME=<your-pinecone-env-name> # Environment name for Pinecone
PINECONE_INDEX_NAME=<your-pinecone-index-name> # Index name for Pinecone

# Langfuse configurations
LANGFUSE_PUBLIC_KEY=<your-langfuse-public-key> # Public key for Langfuse services
LANGFUSE_SECRET_KEY=<your-langfuse-secret-key> # Secret key for Langfuse services
```

Make sure to replace ```<your-secret-key>, <your-upload-service-url>, <your-openai-api-key>, <your-pinecone-api-key>, <your-pinecone-env-name>, <your-pinecone-index-name>, <your-langfuse-public-key>, and <your-langfuse-secret-key>``` with the actual values you've been provided or that you've set up for these services.

**Keep this .env file in the parent folder in your local repo to be secure and do not commit it to public repositories for security reasons.**

2. Ensure Redis server is installed and configured on your machine.

## Running the Application

To run the application, you will need to open three terminals for the different services:

1. **Terminal 1**: Run the development server

    ```bash
    pipenv shell
    inv dev
    ```

    After running, it should display the localhost address (usually `http://localhost:8000`). Open this address in your web browser.

2. **Terminal 2**: Start the Redis server

    ```bash
    redis-server
    ```

3. **Terminal 3**: Run the background worker

    ```bash
    pipenv shell
    inv devworker
    ```
4. **Logging into the localhost server**
Once all services are up, go to the localhost address provided by the development server, create your login details if necessary, and log in. Then, you'll be able to upload a PDF and start asking questions based on that PDF.

## Additional Commands

* To deactivate the virtual environment if you've used `conda`, run:

    ```bash
    conda deactivate
    ```

* To exit pipenv's shell environment, simply type `exit`.

