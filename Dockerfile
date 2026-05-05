# 使用官方 PHP 8.2 FPM 映像檔
FROM php:8.2-fpm

# 安裝系統依賴與 PHP 擴充
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    zip \
    unzip \
    git \
    curl \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install pdo_mysql gd bcmath

# 安裝 Composer
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

# 設定工作目錄
WORKDIR /var/www

# 複製專案檔案
COPY . .

# 安裝 Laravel 依賴
RUN composer install --no-dev --optimize-autoloader

# 設定權限
RUN chown -R www-data:www-data /var/www/storage /var/www/bootstrap/cache

EXPOSE 9000
CMD ["php-fpm"]