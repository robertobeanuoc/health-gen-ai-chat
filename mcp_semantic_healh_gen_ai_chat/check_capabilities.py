#!/usr/bin/env python3
import asyncio
from fastmcp import Client

async def ejecutar_metodos():
    # Inicialización del cliente apuntando al archivo del servidor
    async with Client("main.py") as cliente:
        
        print("--- 1. Ejecutando list_local_metrics ---")
        try:
            # Invocación sin argumentos
            metricas = await cliente.call_tool("list_local_metrics")
            print(metricas)
        except Exception as e:
            print(f"Error: {e}")

        print("\n--- 2. Ejecutando get_dimensions_by_semantic_model ---")
        try:
            # Invocación sin argumentos
            dimensiones = await cliente.call_tool("get_dimensions_by_semantic_model")
            print(dimensiones)
        except Exception as e:
            print(f"Error: {e}")

        print("\n--- 3. Ejecutando get_model_lineage ---")
        try:
            # Invocación con argumentos. Se requiere especificar el nombre del modelo.
            # Sustituya "nombre_del_modelo_objetivo" por un modelo existente en su manifest.json
            argumentos = {"model_name": "nombre_del_modelo_objetivo"}
            linaje = await cliente.call_tool("get_model_lineage", arguments=argumentos)
            print(linaje)
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(ejecutar_metodos())