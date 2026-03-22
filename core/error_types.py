# core/error_types.py
from enum import Enum

class ErrorType(Enum):
    """
    Перечисление для различных типов ошибок в приложении.
    Каждый тип может иметь связанные с ним UI-эффекты и поведение.
    """
    # Ошибки выполнения команд (не критичные для логики приложения)
    COMMAND_EXECUTION = "Command Execution Error" 
    
    # Разовые сетевые ошибки (например, потеря соединения с сервером)
    NETWORK_TRANSIENT = "Transient Network Error" 
    
    # Критические ошибки (требующие отправки логов, но приложение продолжает работу)
    CRITICAL_APPLICATION = "Critical Application Error"
    
    # Обычный статус (нет активных серьезных ошибок)
    NORMAL = "Normal"

    # Находимся в меню запуска
    START = "StartApp" 

    def __str__(self):
        return self.value

class ErrorState(Enum):
    """
    Перечисление для текущего общего состояния ошибок, влияющего на UI.
    """
    OK = "ok" # Зеленый/Нормальный
    START = "start" # Запускаюсь...
    WARNING = "warning" # Желтый/Оранжевый
    SERVER_CONNECT = "placs_server_error" # Розоватый/красненький
    NETWORK = "network_error" # Розоватый/красненький
    CRITICAL = "critical" # Красный

    def __str__(self):
        return self.value