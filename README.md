# Conversational AI System

## Complete System Flowchart
![portfolio_ai_conversational_app_block_diagram (2)](https://github.com/luv91/pdf/assets/10795176/2c3c1ad7-38b0-43e7-bf86-15daa4c098f5)

## FrontPage of the application

![image](https://github.com/luv91/pdf/assets/10795176/2a0d1a0d-9206-4306-bb30-8bde799d8ee5)

## After Logging in, upload a document
![image](https://github.com/luv91/pdf/assets/10795176/f5c2c649-de1c-4b0b-b928-a2d87e8717d9)

## After uploading, document would appear in the list of documents (if any already uploaded)
![image](https://github.com/luv91/pdf/assets/10795176/7357e018-f827-46d4-893c-42421bd6acd4)

## Once uploaded, click View and Start chatting

![image](https://github.com/luv91/pdf/assets/10795176/d71a5542-b04b-460b-858c-d9d6eb2c8b87)

## 
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

## Key Features of the Modular Design

### Component-Based Architecture
The system employs a component-based architecture where each function such as retrieval, language processing, and memory storage is handled by separate, interchangeable components. This modular design enhances the maintainability and scalability of the system, making it easy to upgrade or replace components without affecting the overall functionality.

### Dynamic Component Selection
Components are selected dynamically based on the current conversation context. This flexibility allows the system to adapt to different user needs and scenarios effectively, ensuring optimal performance tailored to each conversation's specific requirements.

### Extensible Component Maps
The use of component maps (`retriever_map`, `llm_map`, `memory_map`) enables easy management and extension of functionalities. Developers can add new capabilities or improve existing ones by simply updating the respective maps without reworking the core logic of the application.

### Streamlined Conversation Management
The system efficiently manages ongoing conversations by storing and retrieving conversation-specific components, ensuring consistency and relevance throughout the user interaction. This streamlined management supports complex conversational capabilities and enhances user experience.

### Scalable Conversation Components
The architecture supports scaling individual components as needed. Whether scaling up the language models for more complex processing, or expanding the memory systems for longer or more detailed conversations, each component can be independently adjusted to meet growing demands.

