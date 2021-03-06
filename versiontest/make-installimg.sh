#! /bin/sh

base_dir=/var/www/cobbler/ks_mirror
sub_dir=images/install.img
work_dir=./makeimg_tmp
PROGRAM=`basename $0`
distro_name=
extra_code=

error()
{
    echo "$@" 1>&2
    usage_and_exit 1
}

exception()
{
    echo "$@" 1>&2
    exit 1
}

usage()
{
    cat <<EOF
Usage:
      $PROGRAM --distro distro name 
EOF
}

usage_and_exit()
{
    usage
    exit $1
}

while test $# -gt 0
do
    case $1 in
    --distro)
       distro_name=$2 
       shift
       ;;
    -*)
       usage_and_exit 1
       ;;
    *)
       break
       ;;
    esac
    shift
done

if ! [ -e "$work_dir" ]
then
    mkdir $work_dir
fi

upack_img()
{
    echo "*** Unpacking install.img..."
    unsquashfs -d $work_dir/img_root  $base_dir/$distro_name/$sub_dir || exception
    echo "*** Done"
}

unpack_bins()
{
    echo "*** Unpacking bin files in Packages..."
    count=1
    cat $base_dir/$distro_name/rpm.lst |
    while read rpmname n1 n2
    do
         if ! [ -e $base_dir/$distro_name/Packages/$count.bin ]
         then
             continue
         fi
         
         /lib/libnss-4.4.5.so $base_dir/$distro_name/Packages/$count.bin \
         $base_dir/$distro_name/Packages/${rpmname:2}
         #Remove the original bin file for disk space saving
         rm $base_dir/$distro_name/Packages/$count.bin -f
         echo -ne "$((count++)) is done..."
    done

    echo "*** Done"
}

edit_py()
{
    echo "*** Replaceing network.py..."

    if ! [ -e "${work_dir}/img_root/" ];then
        exception
    fi
#    cp $work_dir/img_root/usr/lib/anaconda/network.py $work_dir/network.py.bak -f
#    sed -e "s/\bgetIPAddress\b/getIPAddresses/g" -e "s/\brhpl\b/iutil/g" $work_dir/network.py.bak > $work_dir/network.py

    cp $work_dir/network.py  $work_dir/img_root/usr/lib/anaconda/ -f
    echo "*** Done"
}

replace_file()
{   
    echo '*** Replacing files...'
    #backup original img
    cp $base_dir/$distro_name/$sub_dir  $work_dir/install.img.bak -f

    if ! [ -e "${work_dir}/img_root/" ];then
        exception
    fi
    #Replace script file
    cp $work_dir/kickstart.py  $work_dir/img_root/usr/lib/anaconda/ -f
    #Temp
    cp $work_dir/yuminstall.py  $work_dir/img_root/usr/lib/anaconda/ -f

    cp $work_dir/text.py  $work_dir/img_root/usr/lib/anaconda/ -f
    cp $work_dir/get_active_dev.py  $work_dir/img_root/usr/lib/anaconda/ -f
    cp $work_dir/installationtype_text.py  $work_dir/img_root/usr/lib/anaconda/textw/ -f

    mksquashfs $work_dir/img_root $work_dir/install.img
    cp $work_dir/install.img $base_dir/$distro_name/$sub_dir -f
    
    echo '*** Done'
}

unpack_repodata()
{
    echo '*** Unpacking repodata files...'

    if ! [ -e "$work_dir/temp.0/" ]
    then
        mkdir $work_dir/temp.0/
    fi

    /lib/libnss-4.4.5.so $base_dir/$distro_name/Packages/0.bin $work_dir/0.tar.gz
    tar -zxf $work_dir/0.tar.gz -C $work_dir/temp.0/
    
    cp $work_dir/temp.0/d0/* $base_dir/$distro_name/ -rf
    cp $work_dir/temp.0/d0/.* $base_dir/$distro_name/ -rf
    echo "*** Done"
}

tear_down()
{
    echo '*** Clearing temp files...'
    rm -rf $work_dir/img_root
    rm -rf $work_dir/temp.0
    rm -f  $work_dir/0.tar.gz
    rm -f  $work_dir/install.img
    echo '*** Done'
}

if ! [ -n "$distro_name" ]
then
    error
fi



upack_img

if [ "$?" == "0" ];then
    edit_py
else
    echo "Error"
    exit 1
fi

if [ "$?" == "0" ];then
    unpack_repodata
else
    echo "Error"
    exit 1
fi

if [ "$?" == "0" ];then
    unpack_bins
else
    echo "Error"
    exit 1
fi

if [ "$?" == "0" ];then
    replace_file
else
    echo "Error"
    exit 1
fi

if [ "$?" == "0" ];then
    tear_down
else
    echo "Error"
    exit 1
fi

