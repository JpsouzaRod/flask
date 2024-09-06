from flask import Flask, request, jsonify
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from flasgger import Swagger
from dotenv import load_dotenv
import cachetools
import os
from flask_cors import CORS
import google.generativeai as genai

load_dotenv()


def prompt(comentarios):
    return f"""{comentarios}
    crie um resumo das avaliações do produto"""
    
def gerar_resumo(comentarios):
    genai.configure(api_key=os.getenv('API_KEY'))
    model = genai.GenerativeModel(model_name='gemini-1.5-flash')
    response = model.generate_content(prompt(comentarios))
    return response.text

app = Flask(__name__)
swagger = Swagger(app)

# Configuração do CORS
CORS(app, resources={r"/*": {"origins": "*"}})

try:
    client = MongoClient(os.getenv('MONGO_URI'), serverSelectionTimeoutMS=5000)
    db = client[os.getenv('DATABASE_NAME')]
    collection = db[os.getenv('COLLECTION_NAME')]
    client.server_info()  # Testar a conexão
except ServerSelectionTimeoutError:
    print("Erro ao conectar ao MongoDB")
    collection = None

cache = cachetools.TTLCache(maxsize=100, ttl=3600)  # Cache configurado para 1 hora

def filtrar_comentarios(reviews):
    return [avaliacao['avaliacao'] for avaliacao in reviews[:20]]

@app.route('/save_review', methods=['POST'])
def save_review():
    """
    Adiciona uma nova avaliação para um produto no banco de dados.
    ---
    tags:
      - Reviews
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - produto_id
            - nome_usuario
            - nota
            - avaliacao
          properties:
            produto_id:
              type: string
              description: O ID do produto.
            nome_usuario:
              type: string
              description: Nome do usuário que faz a avaliação.
            nota:
              type: integer
              description: Nota dada ao produto.
            avaliacao:
              type: string
              description: Comentário sobre o produto.
    responses:
      201:
        description: Avaliação salva com sucesso.
      400:
        description: Dados inválidos.
      500:
        description: Erro de conexão com o banco de dados.
    """
    if collection is None:
        return jsonify({'error': 'Erro de conexão com o banco de dados'}), 500

    data = request.json
    produto_id = data.get('produto_id')
    nome_usuario = data.get('nome_usuario')
    nota = data.get('nota')
    avaliacao = data.get('avaliacao')

    if not (produto_id and nome_usuario and 1 <= nota <= 5 and avaliacao):
        return jsonify({'error': 'Dados inválidos'}), 400

    review = {
        'produto_id': produto_id,
        'nome_usuario': nome_usuario,
        'nota': nota,
        'avaliacao': avaliacao
    }

    collection.insert_one(review)
    return jsonify({'message': 'Avaliação salva com sucesso'}), 201

@app.route('/get_reviews', methods=['GET'])
def get_reviews():
    """
    Retorna todas as avaliações para um produto específico e o resumo das avaliações.
    ---
    tags:
      - Reviews
    parameters:
      - name: produto_id
        in: query
        type: string
        required: true
        description: O ID do produto.
    responses:
      200:
        description: Uma lista de avaliações e o resumo das avaliações.
        schema:
          type: object
          properties:
            resumo_avaliacao:
              type: string
            media:
              type: number
            avaliacoes:
              type: array
              items:
                type: object
      400:
        description: ID do produto é obrigatório.
      500:
        description: Erro de conexão com o banco de dados.
    """
    if collection is None:
        return jsonify({'error': 'Erro de conexão com o banco de dados'}), 500

    produto_id = request.args.get('produto_id')

    if not produto_id:
        return jsonify({'error': 'ID do produto é obrigatório'}), 400

    reviews = list(collection.find({'produto_id': produto_id}, {'_id': 0}).sort('data', -1))

    if not reviews:
        return jsonify({
            'resumo_avaliacao': 'Nenhum resumo disponível.',
            'media': 0,
            'avaliacoes': []
        }), 200

    notas = [review['nota'] for review in reviews]
    media_nota = round(sum(notas) / len(notas), 2) if notas else 0

    resumo_avaliacao = cache.get(produto_id)
    if not resumo_avaliacao:
        comentarios = filtrar_comentarios(reviews)
        resumo_avaliacao = gerar_resumo(comentarios)
        cache[produto_id] = resumo_avaliacao

    return jsonify({
        'resumo_avaliacao': resumo_avaliacao,
        'media': media_nota,
        'avaliacoes': reviews
    }), 200
    
    
@app.route('/search_words_reviews', methods=['GET'])
def search_reviews():
    """
    Busca por uma palavra específica dentro das avaliações de um produto.
    ---
    tags:
      - Reviews
    parameters:
      - name: produto_id
        in: query
        type: string
        required: true
        description: O ID do produto.
      - name: palavra
        in: query
        type: string
        required: true
        description: A palavra a ser buscada dentro das avaliações.
    responses:
      200:
        description: Uma lista de avaliações que contém a palavra buscada.
        schema:
          type: object
          properties:
            avaliacoes:
              type: array
              items:
                type: object
      400:
        description: ID do produto ou palavra de busca é obrigatória.
      500:
        description: Erro de conexão com o banco de dados.
    """
    if collection is None:
        return jsonify({'error': 'Erro de conexão com o banco de dados'}), 500

    produto_id = request.args.get('produto_id')
    palavra = request.args.get('palavra')

    if not produto_id or not palavra:
        return jsonify({'error': 'ID do produto e palavra de busca são obrigatórios'}), 400

    # Obtém todas as avaliações para o produto
    reviews = list(collection.find({'produto_id': produto_id}, {'_id': 0}).sort('data', -1))

    # Filtra as avaliações que contêm a palavra no campo 'avaliacao'
    filtered_reviews = [review for review in reviews if palavra.lower() in review['avaliacao'].lower()]

    return jsonify({
        'avaliacoes': filtered_reviews
    }), 200


if __name__ == '__main__':
    app.run(debug=True)
